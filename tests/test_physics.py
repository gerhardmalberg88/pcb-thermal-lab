import copy
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from pcb_thermal.power import derive
from pcb_thermal.pipeline import valid_cache,complete
from pcb_thermal.common import WorkflowError

def network():
    components=[]
    for n in range(17):
        tap='GND' if n==0 else '+BATT' if n==16 else '/balance/cell'+str(n)
        components.append({'ref':f'R{n}','value':'20R 2W','pads':[{'net':tap},{'net':f'/balance/CB{n}'}]})
    case={'sources':{'refs':[c['ref'] for c in components],'kind':'balancing','schedule':'automatic','resistance_ohm':20.,'switch_resistance_ohm':1.45,'cell_voltage_v':4.2,'phase_s':5.}}
    return {'components':components},case

class Physics(unittest.TestCase):
    def test_power_against_independent_nodal_circuit(self):
        board,case=network();power=derive(board,case);tap=np.arange(17)*4.2
        for phase,channels in [('odd',range(1,17,2)),('even',range(2,17,2))]:
            a=np.eye(17)/20;b=tap/20
            for n in channels:
                conductance=1/1.45;a[n,n]+=conductance;a[n-1,n-1]+=conductance;a[n,n-1]-=conductance;a[n-1,n]-=conductance
            internal=np.linalg.solve(a,b);loss=(tap-internal)**2/20
            for n in range(17):self.assertAlmostEqual(loss[n],power['resistors'][f'R{n}'][phase+'_w'],places=11)
        self.assertAlmostEqual(power['total_w'],3.2854850045326165)
        self.assertAlmostEqual(power['resistors']['R0']['average_w']*2,power['resistors']['R1']['average_w'])

    def test_reject_wrong_net_and_missing_source(self):
        board,case=network();board['components'][4]['pads'][0]['net']='/balance/cell5'
        with self.assertRaises(WorkflowError):derive(board,case)
        board,case=network();case['sources']['refs'][0]='Rabsent'
        with self.assertRaises(WorkflowError):derive(board,case)

    def test_cache_detects_mutated_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'field').write_text('valid');complete(p,'key');self.assertTrue(valid_cache(p,'key'))
            (p/'field').write_text('altered');self.assertFalse(valid_cache(p,'key'));self.assertFalse(valid_cache(p,'different'))

if __name__=='__main__':unittest.main()

class ExecutionContracts(unittest.TestCase):
    def test_explicit_cpu_never_probes_gpu(self):
        from pcb_thermal.runtime import Runtime
        class CPUOnly(Runtime):
            def image_exists(self,kind):
                self.assert_kind=kind
                return kind=='cpu'
            def gpu_check(self,*args):raise AssertionError('CPU attempted a GPU probe')
        self.assertEqual(CPUOnly().select('cpu')[0],'cpu')

    def test_failed_native_log_not_accepted(self):
        from pcb_thermal.solver import verify_log
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'solver.log'
            for content in ['HeatSolve: starting','ERROR:: HeatSolver failure\nALL DONE','failed to converge\nALL DONE']:
                p.write_text(content)
                with self.assertRaises(WorkflowError):verify_log(p)
