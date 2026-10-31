"""Container-side stages. Binary tool Python environments exchange files."""
import argparse
import json
import shutil
from pathlib import Path
from .common import ROOT,WorkflowError,write_json,call,digest

def audit_conversion(metadata,mesh,log=None):
    expected=json.loads(Path(metadata).read_text());mesh=Path(mesh)
    counts={}
    with (mesh/'mesh.elements').open() as stream:
        for line in stream:
            body=int(line.split()[1]);counts[body]=counts.get(body,0)+1
    if set(counts)!=set(map(int,expected['bodies'])):raise WorkflowError('ElmerGrid changed or dropped body tags')
    bc=set()
    with (mesh/'mesh.boundary').open() as stream:
        for line in stream:bc.add(int(line.split()[1]))
    if 101 not in bc or not bc.issubset({101,102}):raise WorkflowError(f'Unexpected converted boundary tags: {bc}')
    if log and 'There is a single piece in the mesh' not in Path(log).read_text():
        raise WorkflowError('ElmerGrid did not confirm one connected mesh; inspect disconnected solids before solving')
    write_json(mesh/'conversion-audit.json',{'body_element_counts':counts,'boundary_tags':sorted(bc),'tags_preserved':True,'connected_piece_count':1 if log else None})

def main():
    p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('case');p.add_argument('--board');p.add_argument('--backend',default='cpu');p.add_argument('--ranks',type=int,default=1);a=p.parse_args()
    path=Path(a.case);case=json.loads(path.read_text());out=path.parent
    if a.stage=='extract':
        from .extract import extract
        board=extract(a.board,out/'extract/board.json',case['mesh']['chord_mm'])
        args=['kicad-cli','pcb','export','step','--force','--user-origin','0x0mm','--include-tracks','--include-pads','--include-zones','--include-inner-copper','--no-extra-pad-thickness','--component-filter',','.join(case['sources']['refs']),'-o',str(out/'extract/board.step'),a.board]
        call(args)
        from .step import audit_and_export
        alignment=audit_and_export(board,case['sources']['refs'],out/'extract')
        write_json(out/'extract/placements.json',{c['ref']:{'position_mm':c['position'],'angle_deg':c['angle_deg'],'flipped':c['flipped'],'models':c['models']} for c in board['components'] if c['ref'] in case['sources']['refs']})
        write_json(out/'extract/coordinates.json',{'thermal':'saved KiCad x/y, z=0 at front copper top; millimetres until final mesh','step':'KiCad user-origin 0x0mm; y is reversed relative to saved PCB coordinates','step_to_thermal_matrix':alignment['step_to_thermal_matrix_row_major'],'source_sha256':digest(a.board)})
    elif a.stage=='mesh':
        from .power import derive
        from .geometry import mesh
        board=json.loads((out/'extract/board.json').read_text());power=derive(board,case)
        write_json(out/'mesh/power.geometry.json',power)
        mesh(board,case,power,out/'mesh',Path(a.board).parent if a.board else Path('/project'))
    elif a.stage=='solve':
        import numpy as np
        from .power import derive
        from .solver import generate,surface_area
        board=json.loads((out/'extract/board.json').read_text());power=derive(board,case)
        write_json(out/'solve/power.json',power)
        meta=json.loads((out/'mesh/physical-groups.json').read_text())
        area=surface_area(np.load(out/'mesh/mesh.npz'))
        generate(case,power,meta,out/'solve',a.backend,a.ranks,surface_area_m2=area)
        if (out/'solve/case.override.sif').exists():
            text=(out/'solve/case.override.sif').read_text().replace('Mesh DB "." "."','Mesh DB "." "mesh"')
            (out/'solve/case.sif').write_text(text)
            (out/'solve/mesh/case.sif').write_text((out/'solve/case.sif').read_text().replace('Mesh DB "." "mesh"','Mesh DB "." "."'))
    elif a.stage=='compile':
        import os
        from .native import compile_scalars
        compile_scalars(out/'solve')
        lib=Path(os.environ.get('ELMER_HOME','/opt/elmer'))/'share/elmersolver/lib'
        call(['elmerf90','-O2','-shared','-fPIC',ROOT/'src/native/ScheduledHeat.F90',
              '-L'+str(lib),'-l:HeatSolve.so','-Wl,-rpath,'+str(lib),'-o',out/'solve/ScheduledHeat.so'])
        call(['elmerf90','-O2','-shared','-fPIC',ROOT/'src/native/FastAudit.F90','-o',out/'solve/FastAudit.so'])
    elif a.stage=='postprocess':
        from .postprocess import report
        report(out,case)
        if case.get('outputs',{}).get('render',True):call(['xvfb-run','-a','pvpython',ROOT/'scripts/render.py',str(out)])

if __name__=='__main__':main()
