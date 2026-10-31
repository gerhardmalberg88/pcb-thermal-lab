#!/usr/bin/env python3
"""Publish a compact, verified steady snapshot without native meshes or local paths."""
import argparse
import copy
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from pcb_thermal.common import digest, write_json, WorkflowError
from pcb_thermal.study_runner import verified_record, physical_signature


def publish(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    progress = json.loads((root/'study-steady.json').read_text())
    if progress['status'] in ('preparing', 'running'):
        raise WorkflowError('Wait until the study has stopped before publishing')
    reference = None
    cases, rows = [], []
    source = None
    baseline = None
    for item in progress['completed']:
        name = item['case']
        if Path(name).name != name:
            raise WorkflowError('Case identifiers must be directory names')
        folder = root/name
        record = verified_record(folder, reference)
        reference = reference or record
        s = record['summary']
        provenance = json.loads((folder/'provenance.json').read_text())
        resolved = json.loads((folder/'case.resolved.json').read_text())
        source = source or provenance['source']
        resource = s.get('resources') or {}
        rows.append(dict(case=name, schedule=resolved['sources']['schedule'],
                         prediction_status=progress.get('validation_status', 'full_domain_validation_deferred'),
                         h_w_m2k=s['h_w_m2k'], resistor_heat_w=s['resistor_heat_w'],
                         maximum_temperature_c=s['maximum_temperature_c'],
                         board_maximum_c=s['board_maximum_c'],
                         heat_balance_relative_error=s['maximum_heat_balance_relative_error'],
                         solver_wall_seconds=resource.get('wall_seconds'),
                         solver_peak_rss_bytes=resource.get('peak_process_tree_rss_bytes_sampled')))
        stages = {stage:json.loads((folder/stage/'stage.json').read_text()) for stage in
                  ('extract', 'mesh', 'convert', 'solve', 'postprocess')}
        cases.append(dict(case=name, backend=provenance['backend'],
                          solver_image=provenance['solver'], tools_image=provenance['tools'],
                          implementation_sha256=provenance['implementation'],
                          stage_keys={key:value['key'] for key,value in stages.items()},
                          converted_mesh_sha256=record['converted_mesh_hashes'],
                          native_and_report_sha256={f'{stage}/{path}':sha for stage in ('solve','postprocess')
                                                    for path,sha in stages[stage]['artifacts'].items()},
                          completed_unix=provenance['completed_unix']))
        if name == 'automatic-h10': baseline = (folder, resolved)
    if not baseline or not rows:
        raise WorkflowError('A verified automatic-h10 result is needed for the selected figures')
    case = baseline[1]
    detail_snapshot = None
    if progress.get('optional_detail', {}).get('status') in ('pass', 'unconverged'):
        detail_name = progress['optional_detail']['case']
        detail_folder = root/detail_name
        detail_record = verified_record(detail_folder)
        detail_provenance = json.loads((detail_folder/'provenance.json').read_text())
        detail_case = json.loads((detail_folder/'case.resolved.json').read_text())
        normalized = copy.deepcopy(detail_case)
        normalized['geometry']['detail_margin_mm'] = case['geometry']['detail_margin_mm']
        if (detail_provenance['source'] != source or
            physical_signature(normalized, source) != reference['physical_signature'] or
            detail_case['sources']['schedule'] != 'automatic' or detail_case['cooling']['h_w_m2k'] != 10):
            raise WorkflowError('Limited detail comparison differs in more than its detailed-region margin')
        detail_snapshot = dict(case=detail_name, solver_image=detail_provenance['solver'],
                               tools_image=detail_provenance['tools'],
                               physical_inputs={k:detail_case[k] for k in ('analysis','sources','geometry','mesh','materials','cooling','assumptions')},
                               converted_mesh_sha256=detail_record['converted_mesh_hashes'],
                               record_sha256={name:digest(detail_folder/name) for name in
                                              ('case.resolved.json','provenance.json','solve/case.sif','postprocess/summary.json')})
    comparisons = {}
    for name in ('mesh-convergence.json', 'limited-detail-comparison.json'):
        if name == 'limited-detail-comparison.json' and progress.get('optional_detail', {}).get('status') not in ('pass', 'unconverged'):
            continue
        if (root/name).exists():
            def portable(value):
                if isinstance(value, dict): return {k:portable(v) for k,v in value.items()}
                if isinstance(value, list): return [portable(v) for v in value]
                if isinstance(value, str) and value.startswith('/'): return Path(value).name
                return value
            comparisons[name] = portable(json.loads((root/name).read_text()))
    destination.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r['h_w_m2k'], ['automatic','odd','even'].index(r['schedule'])))
    with (destination/'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    for name in ('top.png', 'isometric.png'):
        shutil.copy2(baseline[0]/'postprocess'/name, destination/name)
    shutil.copy2(root/'steady-convection.png', destination/'convection.png')
    snapshot = dict(schema=1, generated_utc=datetime.now(timezone.utc).isoformat(),
                    study_status=progress['status'], completed_cases=len(rows),
                    validation_status=progress.get('validation_status', 'full_domain_validation_deferred'),
                    optional_detail_status=progress.get('optional_detail', {}).get('status'),
                    new_completed=progress['new_completed'],
                    simulation_wall_seconds=progress.get('overall_elapsed_seconds', progress['wall_seconds']),
                    current_attempt_wall_seconds=progress['wall_seconds'],
                    prior_attempts=progress.get('prior_attempts', []),
                    design_source_sha256=source, cases=cases, numerical_comparisons=comparisons,
                    limited_detail_run=detail_snapshot,
                    physical_inputs={k:case[k] for k in ('analysis','sources','geometry','mesh','materials','cooling','assumptions')},
                    scope='Resistor-only CPU steady predictions; completion does not establish full domain convergence, transient behavior, CUDA agreement or hardware correlation',
                    published_sha256={p.name:digest(p) for p in destination.iterdir() if p.is_file() and p.name!='provenance.json'})
    write_json(destination/'provenance.json', snapshot)
    print(f'Published {len(rows)} accepted steady cases and three figures to {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    publish(args.results, args.destination)
