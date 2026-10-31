import json
import tempfile
import unittest
from pathlib import Path
from pcb_thermal.study import compare_runs


class Convergence(unittest.TestCase):
    def fixture(self, root, name, peak=35., history=None):
        out=Path(root)/name/'postprocess';out.mkdir(parents=True)
        data={'analysis':'transient' if history else 'steady','ambient_c':25.,
              'maximum_temperature_c':peak,'board_maximum_c':peak,
              'heat_balance_pass':True,'resistors':[{'reference':'R1','maximum_c':peak}]}
        (out/'summary.json').write_text(json.dumps(data))
        if history:
            (out/'history.csv').write_text('time_s,temperature_max_k,R1_max_k\n'+
                '\n'.join(f'{t},{temp},{temp}' for t,temp in history)+'\n')
        return out.parent

    def test_both_absolute_and_relative_criteria(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.fixture(d,'a',35.3);b=self.fixture(d,'b',35.)
            check=compare_runs(a,b)
            self.assertLess(check['maximum_change_c'],1)
            self.assertFalse(check['pass'])  # 0.3 C is 3% of this 10 C rise.

    def test_warmup_difference_is_not_hidden_by_equal_final_temperature(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.fixture(d,'a',history=[(1,302),(2,300)])
            b=self.fixture(d,'b',history=[(.5,300),(1,303),(1.5,302),(2,300)])
            check=compare_runs(a,b)
            self.assertEqual(check['hotspot_changes_c']['maximum_temperature_c'],0)
            self.assertEqual(check['maximum_change_c'],1)
            self.assertFalse(check['pass'])

    def test_common_times_agree(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.fixture(d,'a',history=[(1,302),(2,300)])
            b=self.fixture(d,'b',history=[(.5,301),(1,302.01),(1.5,301),(2,300)])
            self.assertTrue(compare_runs(a,b)['pass'])
