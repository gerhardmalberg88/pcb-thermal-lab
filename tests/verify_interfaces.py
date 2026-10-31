"""Real Gmsh/ElmerGrid/Elmer checks: two-material continuity and disconnected rejection.

Run: PYTHONPATH=src /usr/bin/python3 tests/verify_interfaces.py
"""
import json,sys,time
from pathlib import Path
from pcb_thermal.common import ROOT,call,write_json,WorkflowError
from pcb_thermal.runtime import Runtime

def worker(out):
 import gmsh,numpy as np
 from pcb_thermal.worker import audit_conversion
 from pcb_thermal.solver import verify_log
 out=Path(out);out.mkdir(parents=True,exist_ok=True);checks={}
 for disconnected in [False,True]:
  path=out/('disconnected' if disconnected else 'interface')
  if path.exists():path.rename(path.with_name(path.name+'-previous-'+str(time.time_ns())))
  path.mkdir()
  gmsh.initialize()
  try:
   gmsh.option.setNumber('General.Terminal',0);gmsh.model.add('two-materials')
   first=gmsh.model.occ.addBox(0,0,0,.5,.1,.1)
   second=gmsh.model.occ.addBox(.6 if disconnected else .5,0,0,.5,.1,.1)
   if not disconnected:gmsh.model.occ.fragment([(3,first)],[(3,second)])
   gmsh.model.occ.synchronize()
   for dim,v in gmsh.model.getEntities(3):
    x=gmsh.model.occ.getCenterOfMass(dim,v)[0];gmsh.model.addPhysicalGroup(3,[v],1 if x<.5 else 2)
   surfaces={101:[],102:[],103:[],104:[]}
   for dim,s in gmsh.model.getEntities(2):
    b=gmsh.model.getBoundingBox(dim,s)
    tag=101 if abs(b[0])<1e-6 and abs(b[3])<1e-6 else 102 if abs(b[0]-1)<1e-6 and abs(b[3]-1)<1e-6 else 103 if abs(b[0]-.5)<1e-6 and abs(b[3]-.5)<1e-6 else 104
    surfaces[101 if disconnected else tag].append(s)
   for tag,ids in surfaces.items():
    if ids:gmsh.model.addPhysicalGroup(2,ids,tag)
   gmsh.option.setNumber('Mesh.MeshSizeMin',.05);gmsh.option.setNumber('Mesh.MeshSizeMax',.05)
   gmsh.model.mesh.generate(3);gmsh.option.setNumber('Mesh.MshFileVersion',2.2);gmsh.write(str(path/'board.msh'))
  finally:gmsh.finalize()
  call(['ElmerGrid','14','2','board.msh','-out','mesh'],cwd=path,log=path/'convert.log')
  if disconnected:
   write_json(path/'groups.json',{'bodies':{'1':{},'2':{}}})
   try:audit_conversion(path/'groups.json',path/'mesh',path/'convert.log')
   except WorkflowError as e:
    checks['disconnected_rejection']={'pass':'connected mesh' in str(e),'message':str(e)}
   else:checks['disconnected_rejection']={'pass':False}
   continue
  sif='''Check Keywords Warn
Header
  Mesh DB "." "mesh"
End
Simulation
  Max Output Level = 4
  Coordinate System = Cartesian 3D
  Simulation Type = Steady State
  Steady State Max Iterations = 1
End
Body 1
  Equation = 1
  Material = 1
  audit_first = Logical True
End
Body 2
  Equation = 1
  Material = 2
  audit_second = Logical True
End
Equation 1
  Active Solvers(2) = 1 2
End
Solver 1
  Equation = Heat Equation
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  Linear System Solver = Direct
  Linear System Direct Method = UMFPACK
  Nonlinear System Max Iterations = 1
  Stabilize = False
End
Solver 2
  Exec Solver = After Timestep
  Equation = Scalars
  Procedure = "ThermalScalars" "SaveScalars"
  Filename = "interface.dat"
  Parallel Reduce = Logical True
  Variable 1 = Temperature
  Operator 1 = boundary int
  Mask Name 1 = interface_audit
  Variable 2 = Temperature
  Operator 2 = area
  Mask Name 2 = interface_audit
  Variable 3 = Temperature
  Operator 3 = body min
  Mask Name 3 = audit_first
  Variable 4 = Temperature
  Operator 4 = body min
  Mask Name 4 = audit_second
End
Material 1
  Heat Conductivity = 1
  Density = 1
  Heat Capacity = 1
End
Material 2
  Heat Conductivity = 10
  Density = 1
  Heat Capacity = 1
End
Boundary Condition 1
  Target Boundaries = 101
  Temperature = 300
End
Boundary Condition 2
  Target Boundaries = 102
  Temperature = 310
End
Boundary Condition 3
  Target Boundaries = 103
  interface_audit = Logical True
End
'''
  from pcb_thermal.native import compile_scalars
  compile_scalars(path)
  (path/'case.sif').write_text(sif);call(['ElmerSolver','case.sif'],cwd=path,log=path/'solver.log');verify_log(path/'solver.log')
  value=np.loadtxt(path/'interface.dat');temperature=float(value[0]/value[1]);expected=300+10*.5/(.5+.5/10)
  rows=[list(map(int,line.split())) for line in (path/'mesh/mesh.boundary').read_text().splitlines() if int(line.split()[1])==103]
  shared=bool(rows) and all(row[2]>0 and row[3]>0 for row in rows)
  checks['two_material_interface']={'temperature_k':temperature,'expected_k':expected,'error_k':abs(temperature-expected),'all_interface_faces_have_two_parents':shared,'pass':shared and abs(temperature-expected)<1e-6}
  mpi=sif.replace('Linear System Solver = Direct','Linear System Solver = Iterative\n  Linear System Iterative Method = CG\n  Linear System Use Hypre = True\n  Linear System Preconditioning = BoomerAMG\n  BoomerAMG Relax Type = 6\n  Linear System Convergence Tolerance = 1e-12\n  Linear System Max Iterations = 1000\n  Linear System Abort Not Converged = True').replace('Filename = "interface.dat"','Filename = "interface-mpi.dat"')
  (path/'mpi.sif').write_text(mpi)
  call(['ElmerGrid','2','2','mesh','-metis','2'],cwd=path,log=path/'partition.log')
  call(['mpirun','-np','2','ElmerSolver_mpi','mpi.sif'],cwd=path,log=path/'mpi.log');verify_log(path/'mpi.log')
  parallel=np.loadtxt(path/'interface-mpi.dat');error=float(np.max(abs(parallel-value)))
  checks['mpi_body_minima']={'minimum_k':parallel[2:].tolist(),'serial_mpi_max_scalar_difference':error,'pass':bool(error<1e-6 and min(parallel[2:])>299.99)}
 write_json(out/'checks.json',checks);print(json.dumps(checks,indent=2))
 if not all(c['pass'] for c in checks.values()):raise WorkflowError('Interface/topology validation failed')

if __name__=='__main__':
 if len(sys.argv)>1:worker(sys.argv[1])
 else:
  out=ROOT/'results/validation/interfaces'
  Runtime().run('cpu',['/usr/bin/python3','/workflow/tests/verify_interfaces.py','/work'],output=out,log=out/'validation.log')
