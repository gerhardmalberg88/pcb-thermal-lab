"""Compare serial or partitioned native Elmer steady fields on identical meshes.

Usage under pvpython: compare_fields.py CPU_RUN CUDA_RUN OUTPUT_DIRECTORY
"""
import json
import sys
from pathlib import Path
import numpy as np
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader, vtkXMLPUnstructuredGridReader
from vtkmodules.util.numpy_support import vtk_to_numpy
from pcb_thermal.common import WorkflowError, digest, write_json


def temperatures(run):
    files=sorted((run/'solve/mesh').glob('temperature*.pvtu')) or sorted((run/'solve/mesh').glob('temperature*.vtu'))
    if len(files)!=1:raise WorkflowError('Backend comparison requires one completed steady field per run')
    r=vtkXMLPUnstructuredGridReader() if files[0].suffix=='.pvtu' else vtkXMLUnstructuredGridReader()
    r.SetFileName(str(files[0]));r.Update();grid=r.GetOutput()
    if not grid.GetNumberOfPoints():raise WorkflowError('Empty native field')
    points=vtk_to_numpy(grid.GetPoints().GetData()).copy()
    values=vtk_to_numpy(grid.GetPointData().GetArray('temperature')).copy()
    del r,grid
    unique,index,inverse=np.unique(points,axis=0,return_index=True,return_inverse=True)
    # Shared MPI nodes may occur in both pieces; verify before discarding copies.
    duplicates=float(np.max(np.abs(values-values[index][inverse])))
    if duplicates>1e-5:raise WorkflowError('Shared MPI node temperatures disagree')
    return unique,values[index],duplicates


def compare(cpu,cuda,destination):
    cpu,cuda,destination=map(Path,(cpu,cuda,destination))
    identical={name:digest(cpu/'convert/mesh'/name)==digest(cuda/'convert/mesh'/name)
               for name in ('mesh.nodes','mesh.elements','mesh.boundary')}
    if not all(identical.values()):raise WorkflowError('Backend runs do not have identical converted meshes')
    a,ta,da=temperatures(cpu);b,tb,db=temperatures(cuda)
    if not np.array_equal(a,b):raise WorkflowError('Native fields contain different node coordinates')
    delta=np.abs(ta-tb);worst=int(np.argmax(delta));error=float(delta[worst])
    check={'identical_mesh_files':identical,'unique_nodes':len(a),
           'maximum_temperature_difference_c':error,'rms_temperature_difference_c':float(np.sqrt(np.mean(delta**2))),
           'worst_node_m':a[worst].tolist(),'shared_node_disagreement_c':[da,db],
           'criterion':'Maximum nodal temperature difference <0.1 C','pass':error<.1}
    write_json(destination/'checks.json',check);print(json.dumps(check,indent=2))
    if not check['pass']:raise WorkflowError('CPU/CUDA field comparison exceeds 0.1 C')


if __name__=='__main__':compare(*sys.argv[1:])
