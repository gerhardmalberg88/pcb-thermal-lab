import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from pcb_thermal.common import ROOT, WorkflowError, digest, write_json
from pcb_thermal.pipeline import complete, STAGES, run
from pcb_thermal.runtime import Runtime
from pcb_thermal.study_runner import BudgetExceeded, Progress, steady_cases, time_limit, verified_record, study


class BoundedStudy(unittest.TestCase):
    def test_direct_run_records_resolvable_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = json.loads((ROOT/'examples/layered-via/case.json').read_text())
            case.update(project_root='.', board='board.kicad_pcb', output='output')
            (root/'board.kicad_pcb').write_text('(kicad_pcb)')
            write_json(root/'case.json', case)
            runtime = Mock()
            runtime.engine = 'podman'; runtime.image_id.return_value = 'test-image'
            def extract(*args, **kwargs):
                (Path(kwargs['output'])/'extract/artifact.txt').write_text('fixture extraction')
            runtime.run.side_effect = extract
            with patch('pcb_thermal.pipeline.CACHE', root/'cache'), patch('pcb_thermal.common.CACHE', root/'cache'):
                out = run(root/'case.json', stage='extract', runtime=runtime)
            saved = json.loads((out/'case.resolved.json').read_text())
            self.assertEqual(saved['project_root'], str(root))
            self.assertEqual(saved['board'], str(root/'board.kicad_pcb'))
            self.assertEqual(saved['output'], str(out))
            self.assertEqual(saved, json.loads((out/'provenance.json').read_text())['case'])

    def test_first_case_allowance_cannot_be_extended(self):
        for value in (0, -1, 21, float('nan')):
            with self.assertRaisesRegex(WorkflowError, 'first-case allowance'):
                study('unused.json', first_case_minutes=value)

    def fixture(self, root):
        root = Path(root)
        source = root/'source.kicad_pcb'; source.write_text('saved design')
        folder = root/'automatic-h10'; folder.mkdir()
        write_json(folder/'case.resolved.json', dict(project_root=str(root), analysis='steady',
                   geometry={}, mesh={}, materials={}, cooling={'h_w_m2k':10},
                   sources={'kind':'balancing', 'schedule':'automatic'}))
        write_json(folder/'provenance.json', dict(status='complete', source_preserved=True,
                   backend='cpu', source={'source.kicad_pcb':digest(source)},
                   case=json.loads((folder/'case.resolved.json').read_text())))
        for stage in STAGES:
            (folder/stage).mkdir(); (folder/stage/'data').write_text(stage)
        (folder/'convert/mesh').mkdir()
        for name in ('mesh.nodes', 'mesh.elements', 'mesh.boundary'):
            (folder/'convert/mesh'/name).write_text(name)
        (folder/'solve/solver.log').write_text('ALL DONE\n')
        write_json(folder/'postprocess/summary.json', dict(heat_balance_pass=True,
                   maximum_heat_balance_relative_error=1e-8))
        for stage in STAGES: complete(folder/stage, 'fixture')
        return folder

    def test_historical_inputs_and_mesh_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            record = verified_record(folder)
            changed = dict(record, converted_mesh_hashes={'mesh.nodes':'different'})
            with self.assertRaisesRegex(WorkflowError, 'differs'):
                verified_record(folder, changed)
            (Path(directory)/'source.kicad_pcb').write_text('edited design')
            with self.assertRaisesRegex(WorkflowError, 'Design inputs changed'):
                verified_record(folder)

    def test_mutated_historical_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            (folder/'convert/mesh/mesh.nodes').write_text('damaged')
            with self.assertRaisesRegex(WorkflowError, 'Changed or missing convert'):
                verified_record(folder)

    def test_changed_saved_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            case = json.loads((folder/'case.resolved.json').read_text())
            case['materials'] = {'changed': True}
            write_json(folder/'case.resolved.json', case)
            with self.assertRaisesRegex(WorkflowError, 'configuration differs'):
                verified_record(folder)

    def test_manual_sif_override_is_not_assumed_equivalent(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            (folder/'solve/case.override.sif').write_text('manually edited model')
            with self.assertRaisesRegex(WorkflowError, 'manual SIF overrides'):
                verified_record(folder)

    def test_requested_schedules_and_priority(self):
        self.assertEqual(steady_cases(['odd', 'even']), [
            ('odd', 10), ('even', 10), ('odd', 5), ('even', 5),
            ('odd', 50), ('even', 50), ('odd', 20), ('even', 20)])
        for invalid in ([], ['odd', 'odd'], ['unknown']):
            with self.assertRaises(WorkflowError): steady_cases(invalid)

    def test_deadline_interrupts_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(BudgetExceeded):
            with time_limit(.02): time.sleep(.2)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_failed_progress_keeps_completed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = Progress(directory, ['odd', 'even'], 120)
            progress.add({'case': 'odd-h10', 'summary': {}}, new=True)
            progress.save('running', 'even-h10', report=False)
            progress.save('budget_exhausted', error='deadline', report=False)
            saved = json.loads((Path(directory)/'study-steady.json').read_text())
            self.assertEqual(saved['completed'][0]['case'], 'odd-h10')
            self.assertEqual(saved['new_completed'], ['odd-h10'])
            self.assertEqual(saved['status'], 'budget_exhausted')

    @patch('pcb_thermal.runtime.subprocess.run')
    def test_cleanup_targets_only_owned_containers(self, execute):
        execute.return_value = subprocess.CompletedProcess([], 0, 'owned1\nowned2\n', '')
        Runtime('podman').stop_batch('unique-batch')
        self.assertEqual(execute.call_args_list[0].args[0], [
            'podman', 'ps', '-aq', '--filter', 'label=pcb-thermal.batch=unique-batch'])
        self.assertEqual(execute.call_args_list[1].args[0], [
            'podman', 'rm', '-f', '-t', '5', 'owned1', 'owned2'])

    @patch('pcb_thermal.runtime.call', side_effect=BudgetExceeded('deadline'))
    @patch.object(Runtime, 'stop_container')
    def test_interrupted_client_stops_its_container(self, stop, execute):
        with patch.dict(os.environ, {'PCB_THERMAL_BATCH_ID': 'unique-batch'}):
            with self.assertRaises(BudgetExceeded): Runtime('podman').run('cpu', ['sleep', '10'])
        args = execute.call_args.args[0]
        self.assertIn('pcb-thermal.batch=unique-batch', args)
        stop.assert_called_once_with(args[args.index('--name')+1])

    @patch('pcb_thermal.runtime.subprocess.run')
    def test_docker_cleanup_uses_supported_remove_options(self, execute):
        execute.return_value = subprocess.CompletedProcess([], 0, 'owned\n', '')
        runtime = Runtime('docker')
        runtime.stop_batch('unique-batch')
        self.assertEqual(execute.call_args.args[0], ['docker', 'rm', '-f', 'owned'])
        runtime.stop_container('owned-single')
        self.assertEqual(execute.call_args.args[0], ['docker', 'rm', '-f', 'owned-single'])
