"""Check snapped artificial cut faces against an analytical boundary area.

Run after the layered-via example: PYTHONPATH=src python3 tests/verify_crop_boundaries.py
The outer process uses the normal serialized tools-container workflow.
"""
import json
import sys
from pathlib import Path
import numpy as np
from pcb_thermal.common import ROOT,WorkflowError,write_json,serial_workflow

def worker():
    from pcb_thermal.geometry import mesh
    root=Path('/work')
    example=ROOT/'results/examples/layered-via'
    board=json.loads((example/'extract/board.json').read_text())
    case=json.loads((example/'case.resolved.json').read_text())
    case['geometry'].update(mode='crop',crop_mm=[2.000049,0,18.000049,15])
    power=json.loads((example/'solve/power.json').read_text())
    mesh(board,case,power,root/'mesh')
    data=np.load(root/'mesh/mesh.npz');points=data['nodes'];cuts=data['quads'][data['quad_ids']==102]
    q=points[cuts]
    area=float((np.linalg.norm(np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0]),axis=1)+np.linalg.norm(np.cross(q[:,2]-q[:,0],q[:,3]-q[:,0]),axis=1)).sum()/2)
    thickness=max(l['z_top_mm'] for l in board['stackup'])-min(l['z_bottom_mm'] for l in board['stackup'])
    expected=2*15*thickness*1e-6
    # Exactly the two new x faces are insulated. Original y edges and via walls
    # must remain exposed; their quad normals are not parallel to the x axis.
    xfaces=bool(len(cuts) and np.all(np.ptp(q[:,:,0],axis=1)<1e-12) and np.all(np.minimum(abs(q[:,:,0]-.002),abs(q[:,:,0]-.018))<1e-12))
    check={'artificial_face_count':len(cuts),'insulated_area_m2':area,'expected_area_m2':expected,'only_new_x_cuts_insulated':xfaces,'pass':xfaces and abs(area-expected)/expected<1e-10}
    write_json(root/'checks.json',check);print(check)
    if not check['pass']:raise WorkflowError('Snapped crop boundary tags failed the analytical area check')

@serial_workflow
def launch():
    from pcb_thermal.runtime import Runtime
    out=ROOT/'results/validation/crop-boundaries';out.mkdir(parents=True,exist_ok=True)
    Runtime().run('tools',['/usr/bin/python3','/workflow/tests/verify_crop_boundaries.py','--worker'],output=out,log=out/'check.log',memory_gib=2)

if __name__=='__main__':
    worker() if '--worker' in sys.argv else launch()
