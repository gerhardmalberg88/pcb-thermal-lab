"""Numerical references and runtime checks; a successful build is not validation."""
import json
import math
import shutil
import sys
from pathlib import Path
from .common import ROOT,WorkflowError,call,write_json
from .runtime import Runtime

def reference_mesh(path):
    import gmsh
    path=Path(path);path.mkdir(parents=True,exist_ok=True);gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0);gmsh.model.add('unit-slab')
        volume=gmsh.model.occ.addBox(0,0,0,1,.1,.1);gmsh.model.occ.synchronize()
        gmsh.model.addPhysicalGroup(3,[volume],1)
        for dim,s in gmsh.model.getBoundary([(3,volume)],oriented=False):
            bounds=gmsh.model.getBoundingBox(2,s)
            tag=101 if abs(bounds[0])<1e-6 and abs(bounds[3])<1e-6 else 102
            existing=gmsh.model.getEntitiesForPhysicalGroup(2,tag).tolist() if (2,tag) in gmsh.model.getPhysicalGroups() else []
            if existing:gmsh.model.removePhysicalGroups([(2,tag)])
            gmsh.model.addPhysicalGroup(2,existing+[s],tag)
        gmsh.option.setNumber('Mesh.MeshSizeMin',.05);gmsh.option.setNumber('Mesh.MeshSizeMax',.05)
        gmsh.model.mesh.generate(3);gmsh.option.setNumber('Mesh.MshFileVersion',2.2);gmsh.write(str(path/'reference.msh'))
    finally:gmsh.finalize()
    call(['ElmerGrid','14','2','reference.msh','-out','mesh'],cwd=path,capture=True)

def reference_sif(transient=False,backend='cpu'):
    linear='Linear System Solver = amgx\n  AMGX Config = String "amgx.json"' if backend=='cuda' else 'Linear System Solver = Direct\n  Linear System Direct Method = UMFPACK'
    timing='Simulation Type = Transient\n  Timestepping Method = BDF\n  BDF Order = 1\n  Timestep Intervals = 200\n  Timestep Sizes = 0.05\n  Output Intervals = 200' if transient else 'Simulation Type = Steady State\n  Steady State Max Iterations = 1'
    # 1D slab: T(x)=300 + 2*x-x*x. Density=2 tests per-mass Heat Source.
    condition='External Temperature = 300\n  Heat Transfer Coefficient = 0.01\n  Heat Flux BC = Logical True' if transient else 'Temperature = 300'
    other=condition if transient else 'Heat Flux = 0'
    return f'''Check Keywords Warn
Header
  Mesh DB "." "mesh"
End
Simulation
  Max Output Level = 3
  Coordinate System = Cartesian 3D
  {timing}
  Output File = "reference.result"
  Output File Final Only = Logical True
  Post File = "reference.vtu"
End
Body 1
  Equation = 1
  Material = 1
  Body Force = 1
  Initial Condition = 1
End
Equation 1
  Active Solvers(2) = 1 2
End
Solver 1
  Equation = Heat Equation
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  {linear}
  Linear System Convergence Tolerance = 1e-12
  Linear System Max Iterations = 2000
  Linear System Abort Not Converged = True
  Nonlinear System Max Iterations = 1
  Stabilize = False
End
Solver 2
  Exec Solver = After Timestep
  Equation = Scalars
  Procedure = "SaveData" "SaveScalars"
  Filename = "reference.dat"
  Variable 1 = Time
  Variable 2 = Temperature
  Operator 2 = max
  Variable 3 = Temperature
  Operator 3 = min
End
Material 1
  Heat Conductivity = {100 if transient else 1}
  Density = {1 if transient else 2}
  Heat Capacity = 1
End
Body Force 1
  Heat Source = {0 if transient else 1}
End
Initial Condition 1
  Temperature = {350 if transient else 300}
End
Boundary Condition 1
  Target Boundaries = 101
  {condition}
End
Boundary Condition 2
  Target Boundaries = 102
  {other}
End
'''

def references(directory,backend='cpu'):
    import numpy as np
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);checks={}
    for name,transient in [('conduction',False),('cooling',True)]:
        path=directory/name
        if path.exists():
            import time
            path.rename(directory/(name+'-previous-'+str(time.time_ns())))
        reference_mesh(path);(path/'case.sif').write_text(reference_sif(transient,backend))
        from .solver import amgx_configuration,verify_log
        write_json(path/'amgx.json',amgx_configuration())
        call(['ElmerSolver','case.sif'],cwd=path,log=path/'solver.log')
        verify_log(path/'solver.log')
        data=np.atleast_2d(np.loadtxt(path/'reference.dat'));maximum=float(data[-1,1]);time=float(data[-1,0])
        # V=.01 m³, A=.42 m², h=.01, rho*cp=1 -> tau=V/(h*A).
        expected=300+50*math.exp(-time*.01*.42/.01) if transient else 301.
        error=abs(maximum-expected);checks[name]={'measured_k':maximum,'expected_k':expected,'error_k':error,'pass':error<.15 if transient else error<.005}
        write_json(directory/'checks.json',checks)
    if not all(v['pass'] for v in checks.values()):raise WorkflowError(f'Numerical references failed: {checks}')
    return checks

def doctor(backend='cpu',full=False):
    rt=Runtime();selected,reason=rt.select(backend);print(reason)
    checks={};dest=ROOT/'results/validation'/('doctor-'+selected);dest.mkdir(parents=True,exist_ok=True)
    for name,kind,command in [('kicad','tools',['kicad-cli','version']),('gmsh','tools',['gmsh','--version']),('elmer','cpu',['ElmerSolver','-v']),('paraview','tools',['pvpython','--version'])]:
        r=rt.run(kind,command,capture=True,check=False);checks[name]={'exit_code':r.returncode,'output':r.stdout+r.stderr}
    if full:
        rt.run(selected,['/usr/bin/python3','-m','pcb_thermal.validation','/work',selected],output=dest,log=dest/'doctor.log',gpu_count=1 if selected=='cuda' else 0)
        checks['numerical']=json.loads((dest/'checks.json').read_text())
    write_json(dest/'doctor.json',checks)
    return 0 if all(v.get('exit_code',0)==0 for v in checks.values()) else 1

if __name__=='__main__':references(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'cpu')
