import copy
import unittest
from pcb_thermal.common import WorkflowError
from pcb_thermal.geometry import stack_levels,layer_at_height


class StackMesh(unittest.TestCase):
    def test_only_same_named_dielectric_subplies_merge(self):
        stack=[{'name':name,'kind':kind,'z_bottom_mm':lo,'z_top_mm':hi} for name,kind,lo,hi in [
            ('B.Cu','copper',0,.035),('dielectric 1','dielectric',.035,.155),
            ('dielectric 1','dielectric',.155,.275),('In1.Cu','copper',.275,.293),
            ('dielectric 2','dielectric',.293,.413),('dielectric 3','dielectric',.413,.533),
            ('F.Cu','copper',.533,.568),('F.Mask','soldermask',.568,.603)]]
        original=copy.deepcopy(stack)
        full,_=stack_levels(stack)
        merged,removed=stack_levels(list(reversed(stack)),True)
        self.assertEqual(full-merged,{.155})
        self.assertEqual(removed,[{'layer':'dielectric 1','z_mm':.155}])
        self.assertEqual(stack,original)
        self.assertTrue({0,.035,.275,.293,.413,.533,.568,.603}.issubset(merged))

    def test_does_not_accept_a_quoted_false_as_enabled(self):
        with self.assertRaises(WorkflowError):stack_levels([],"false")

    def test_merged_midpoint_on_saved_ply_edge_retains_material(self):
        stack=[{'name':'dielectric 1','kind':'dielectric','z_bottom_mm':lo,'z_top_mm':hi}
               for lo,hi in [(0.,1.),(1.,2.)]]
        stack.append({'name':'F.Cu','kind':'copper','z_bottom_mm':2.,'z_top_mm':2.035})
        thickness=[]
        for merge in (False,True):
            levels,_=stack_levels(stack,merge)
            totals={}
            for lo,hi in zip(sorted(levels),sorted(levels)[1:]):
                layer=layer_at_height(stack,(lo+hi)/2)
                self.assertIsNotNone(layer)
                totals[layer['kind']]=totals.get(layer['kind'],0)+(hi-lo)
            thickness.append(totals)
        self.assertEqual(thickness[0],thickness[1])
        self.assertEqual(layer_at_height(stack,1.)['kind'],'dielectric')
        self.assertEqual(layer_at_height(stack,2.)['kind'],'copper')
