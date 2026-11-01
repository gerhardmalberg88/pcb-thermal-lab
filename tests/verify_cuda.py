"""Compare real CPU/CUDA temperatures on an identical layered-via mesh.

Run after the CPU example and CUDA doctor: PYTHONPATH=src python3 tests/verify_cuda.py
"""
import json,sys
from pathlib import Path
from pcb_thermal.common import ROOT,write_json,WorkflowError

def compare(root):
 import numpy as np
 from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader
 from vtkmodules.util.numpy_support import vtk_to_numpy
 root=Path(root)
 fields=[];points=[]
 for label in ['cpu','cuda']:
  r=vtkXMLUnstructuredGridReader();r.SetFileName(str(root/(label+'.vtu')));r.Update();data=r.GetOutput()
  fields.append(vtk_to_numpy(data.GetPointData().GetArray('temperature')))
  points.append(vtk_to_numpy(data.GetPoints().GetData()))
 if not np.array_equal(points[0],points[1]):raise WorkflowError('CPU/CUDA field node ordering or geometry differs')
 error=float(np.max(np.abs(fields[0]-fields[1])))
 check={'maximum_temperature_difference_c':error,'same_node_coordinates':True,'pass':error<.1}
 write_json(root/'checks.json',check);print(check)
 if not check['pass']:raise WorkflowError('CPU/CUDA comparison exceeds 0.1 C')

if __name__=='__main__':
 if len(sys.argv)>1:compare(sys.argv[1])
 else:
  import shutil
  from pcb_thermal.config import load
  from pcb_thermal.pipeline import run
  from pcb_thermal.runtime import Runtime
  src=ROOT/'results/examples/layered-via';out=ROOT/'results/validation/cuda-layered-via';checkdir=ROOT/'results/validation/cpu-cuda'
  path,case,project,board,_=load(ROOT/'examples/layered-via/case.json')
  case.update(project_root=str(project),board=str(board),output=str(out),name='CUDA layered-via comparison')
  inputs=ROOT/'.cache/verification-inputs';inputs.mkdir(parents=True,exist_ok=True)
  path=inputs/'cuda-layered-via.json';write_json(path,case)
  run(path,backend='cuda',mpi_ranks=1)
  checkdir.mkdir(exist_ok=True)
  for label,folder in [('cpu',src),('cuda',out)]:
   files=list((folder/'solve/mesh').glob('temperature_t*.vtu'))
   if len(files)!=1:raise WorkflowError('Expected one serial steady field per comparison case')
   shutil.copy2(files[0],checkdir/(label+'.vtu'))
  Runtime().run('tools',['pvpython','/workflow/tests/verify_cuda.py','/work'],output=checkdir,log=checkdir/'compare.log')
