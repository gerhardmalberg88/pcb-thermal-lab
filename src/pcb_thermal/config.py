"""Versioned case validation and source/output ownership."""
import copy
import math
from pathlib import Path
from .common import WorkflowError, read_config, positive

def number(value, name, minimum=0, strict=True):
    if isinstance(value, bool): raise WorkflowError(f'{name} must be numeric')
    x = float(value)
    if not math.isfinite(x) or (x <= minimum if strict else x < minimum):
        raise WorkflowError(f'{name} must be finite and {">" if strict else ">="} {minimum}')
    return x

def load(path, overrides=None):
    path = Path(path).resolve(); case = copy.deepcopy(read_config(path))
    if case.get('schema') != 1: raise WorkflowError('Case schema must be 1')
    project = (path.parent / case.get('project_root', '.')).resolve()
    board = (path.parent / case['board']).resolve()
    if not board.is_file() or not board.is_relative_to(project):
        raise WorkflowError(f'Board must exist within project_root: {board}')
    output = (path.parent / case.get('output', 'results/'+path.stem)).resolve()
    if output == project or project.is_relative_to(output) or output == board.parent:
        raise WorkflowError('Output must be a dedicated results directory')
    if path.is_relative_to(output) or board.is_relative_to(output):
        raise WorkflowError('Output must not contain input files')
    e = case.setdefault('execution', {})
    e.setdefault('backend', 'auto'); e.setdefault('mpi_ranks', 2)
    e.setdefault('threads_per_rank', 1); e.setdefault('gpu_count', 1)
    for key,value in (overrides or {}).items():
        if value is not None: e[key] = value
    if e['backend'] not in ('cpu','cuda','auto'): raise WorkflowError('Unknown backend')
    for key in ('mpi_ranks','threads_per_rank','gpu_count'): e[key] = positive(e[key])
    e.setdefault('cpu_solver','hypre')
    e.setdefault('max_memory_gib',8.0)
    if e['cpu_solver'] not in ('hypre','cholmod'):raise WorkflowError('execution.cpu_solver must be hypre or cholmod')
    if 'max_memory_gib' in e:number(e['max_memory_gib'],'execution.max_memory_gib')
    if case.get('analysis','steady') not in ('steady','transient'): raise WorkflowError('Unknown analysis')
    case.setdefault('analysis','steady')
    g = case.setdefault('geometry', {})
    g.setdefault('mode','hybrid'); g.setdefault('detail_margin_mm',10.0); g.setdefault('tile_mm',5.0)
    if g['mode'] not in ('hybrid','explicit','crop'): raise WorkflowError('Unknown geometry mode')
    if g['mode']=='crop' and len(g.get('crop_mm',[]))!=4: raise WorkflowError('crop needs crop_mm: [xmin,ymin,xmax,ymax]')
    if g['mode']=='crop':
        x0,y0,x1,y1=map(float,g['crop_mm'])
        if not all(math.isfinite(x) for x in (x0,y0,x1,y1)) or x1<=x0 or y1<=y0:
            raise WorkflowError('crop_mm needs finite, increasing bounds')
    for k in ('detail_margin_mm','tile_mm'): number(g[k],k)
    mesh=case.setdefault('mesh',{}); mesh.setdefault('fine_mm',0.5);mesh.setdefault('coarse_mm',3.0)
    mesh.setdefault('scale',1.0);mesh.setdefault('chord_mm',0.01)
    for k in ('fine_mm','coarse_mm','scale','chord_mm'): number(mesh[k],k)
    if 'overlay_grid_mm' in mesh:number(mesh['overlay_grid_mm'],'overlay_grid_mm')
    if mesh['fine_mm']>mesh['coarse_mm']:raise WorkflowError('fine_mm must not exceed coarse_mm')
    cooling=case.setdefault('cooling',{});cooling.setdefault('ambient_c',25.0);cooling.setdefault('h_w_m2k',10.0)
    number(cooling['ambient_c'],'ambient_c',-273.15);number(cooling['h_w_m2k'],'h_w_m2k')
    if cooling.get('radiation',False): raise WorkflowError('Radiation is not enabled in this convection-only model')
    for name in ('copper','fr4','soldermask','resistor','terminal','solder'):
        if name not in case.get('materials',{}):raise WorkflowError('Missing material: '+name)
    for name,material in case['materials'].items():
        if isinstance(material['k'],(int,float)):material['k']=[material['k']]*3
        if len(material['k'])!=3:raise WorkflowError('Material k needs three diagonal conductivities')
        for v in material['k']:number(v,name+'.k')
        for k in ('density','heat_capacity'):number(material[k],name+'.'+k)
    sources=case.get('sources',{})
    outputs=case.setdefault('outputs',{})
    if 'line_mm' in outputs:
        points=outputs['line_mm']
        if len(points)!=2 or any(len(p)!=3 for p in points) or not all(math.isfinite(float(v)) for p in points for v in p):
            raise WorkflowError('outputs.line_mm needs two finite [x,y,z] endpoints in thermal coordinates')
    if 'line_divisions' in outputs:outputs['line_divisions']=positive(outputs['line_divisions'])
    refs=sources.get('refs',[])
    if not refs or len(set(refs))!=len(refs): raise WorkflowError('sources.refs must be a nonempty unique list')
    if sources.get('kind','balancing') not in ('balancing','watts'):raise WorkflowError('sources.kind must be balancing or watts')
    if sources.get('kind','balancing')=='balancing':
        if sources.get('schedule','automatic') not in ('automatic','odd','even'):raise WorkflowError('Only automatic, odd and even schedules are supported')
        for k,v in [('cell_voltage_v',4.2),('resistance_ohm',20.0),('switch_resistance_ohm',1.45),('phase_s',5.0)]:
            sources.setdefault(k,v);number(sources[k],k)
    if case['analysis']=='transient':
        t=case.setdefault('transient',{})
        for k,v in [('on_s',1800.0),('off_s',1800.0),('step_s',1.0),('field_interval_s',5.0)]:
            t.setdefault(k,v);number(t[k],k)
        phase=sources.get('phase_s',5)
        for interval in (phase,t['on_s'],t['off_s'],t['field_interval_s']):
            if abs(interval/t['step_s']-round(interval/t['step_s']))>1e-8:
                raise WorkflowError('Timestep must divide phase, on/off durations and field interval')
    return path,case,project,board,output
