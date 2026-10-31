"""Losslessly compress native VTU arrays, verifying every array before replacement.

Run under pvpython. A transient watcher starts before Elmer and terminates when
.solver-active disappears. Atomic replacement occurs only after a complete VTU
has been written. Native PVTU/PVD filenames and data remain unchanged.
"""
import hashlib,json,sys,time
from pathlib import Path
import vtk
from vtk.util.numpy_support import vtk_to_numpy
root=Path(sys.argv[1]);watch='--watch' in sys.argv;manifest=root/'field-compression.json'
records=json.loads(manifest.read_text()) if manifest.exists() else {}
def signature(grid):
    arrays=[grid.GetPoints().GetData(),grid.GetCells().GetConnectivityArray(),grid.GetCells().GetOffsetsArray(),grid.GetCellTypesArray()]
    for data in (grid.GetPointData(),grid.GetCellData(),grid.GetFieldData()):
        arrays.extend(data.GetArray(i) for i in range(data.GetNumberOfArrays()))
    return [(a.GetName(),a.GetDataTypeAsString(),a.GetNumberOfComponents(),hashlib.sha256(vtk_to_numpy(a).tobytes()).hexdigest()) for a in arrays if a is not None]
while True:
    active=(root/'.solver-active').exists()
    if active and time.time()-(root/'.solver-active').stat().st_mtime>60:
        print('Solver heartbeat expired; finishing complete fields and exiting',flush=True)
        active=False
    for p in sorted((root/'mesh').glob('temperature*.vtu')):
        if str(p.name) in records:continue
        with p.open('rb') as f:
            if p.stat().st_size<100:continue
            f.seek(max(0,p.stat().st_size-128));end=f.read()
        if b'</VTKFile>' not in end:continue
        reader=vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(p));reader.Update();grid=reader.GetOutput()
        if grid.GetNumberOfPoints()==0:raise RuntimeError('Cannot read native VTU '+str(p))
        before=signature(grid);temp=p.with_suffix('.compressed.vtu.tmp');original_size=p.stat().st_size
        original_hash=hashlib.sha256(p.read_bytes()).hexdigest()
        writer=vtk.vtkXMLUnstructuredGridWriter();writer.SetFileName(str(temp));writer.SetInputData(grid)
        writer.SetDataModeToAppended();writer.SetCompressorTypeToZLib();writer.SetCompressionLevel(3);writer.EncodeAppendedDataOff()
        if not writer.Write():raise RuntimeError('VTU compression write failed')
        check=vtk.vtkXMLUnstructuredGridReader();check.SetFileName(str(temp));check.Update()
        if signature(check.GetOutput())!=before:raise RuntimeError('VTU compression changed array values')
        temp.replace(p)
        records[p.name]={'original_sha256':original_hash,'compressed_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                         'original_bytes':original_size,'compressed_bytes':p.stat().st_size,'all_arrays_exact':True}
        temporary=manifest.with_suffix('.tmp');temporary.write_text(json.dumps(records,indent=2)+'\n');temporary.replace(manifest)
        print('Lossless VTU compression:',p.name,original_size,'->',p.stat().st_size,flush=True)
    if not watch or not active:break
    time.sleep(2)
