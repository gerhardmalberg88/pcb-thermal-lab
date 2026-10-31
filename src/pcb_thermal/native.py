"""Compile a narrowly patched native Elmer scalar writer, retaining its license."""
import os
from pathlib import Path
from .common import ROOT,WorkflowError,call,digest,write_json

def compile_scalars(out):
    out=Path(out)
    candidates=[Path('/opt/elmer-source')]+list((ROOT/'.cache/src').glob('elmerfem-*'))
    source=next((p/'fem/src/modules/SaveData/SaveScalars.F90' for p in candidates
                 if (p/'fem/src/modules/SaveData/SaveScalars.F90').is_file()),None)
    if source is None:raise WorkflowError('Pinned Elmer source is required to compile the corrected native scalar writer')
    original=source.read_text()
    needle='    IF(sumi == 0) RETURN'
    # VectorStatistics initialized its return value to zero, corrupting MPI
    # minima for bodies entirely absent on a partition. Use neutral extrema.
    start=original.index('  FUNCTION VectorStatistics(')
    end=original.index('  END FUNCTION VectorStatistics',start)
    before=original[:start];body=original[start:end];after=original[end:]
    if body.count(needle)!=1:raise WorkflowError('Unexpected Elmer SaveScalars revision; review the empty-partition patch')
    patched=before+body.replace(needle,'''    IF(sumi == 0) THEN
      SELECT CASE(OperName)
      CASE('min','min abs')
        operx = HUGE(operx)
      CASE('max')
        operx = -HUGE(operx)
      END SELECT
      RETURN
    END IF''',1)+after
    dest=out/'native';dest.mkdir(exist_ok=True)
    target=dest/'SaveScalars.F90';target.write_text(patched)
    write_json(dest/'patch.json',{'upstream':'Elmer 26.1 SaveScalars.F90','source_sha256':digest(source),
               'patched_sha256':digest(target),'change':'Use neutral extrema on empty MPI partitions; preserve all other native scalar behavior'})
    call(['elmerf90','-O2','-shared','-fPIC',target,'-o',out/'ThermalScalars.so'])
