"""Audit KiCad STEP alignment and export separate, canonical CAD views."""
import math,re
from pathlib import Path
from .common import WorkflowError,write_json

def audit_and_export(board,refs,directory):
    import gmsh
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    directory=Path(directory)
    outline=unary_union([Polygon(p['outer'],p['holes']) for p in board['outline']])
    copper=[l for l in board['stackup'] if l['kind']=='copper']
    # KiCad STEP's z=0 is the core/bottom-copper interface. Our z=0 is
    # front-copper top. This follows the actual saved physical stackup.
    offset=-next(l['z_top_mm'] for l in copper if l['name']=='B.Cu')
    expected=[list(outline.bounds[:2]),list(outline.bounds[2:])]
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.model.occ.importShapes(str(directory/'board.step'));gmsh.model.occ.synchronize()
        entities=gmsh.model.getEntities(3);records=[];groups={'pcb':[],'copper':[],'resistors':[]};positions={}
        for dim,tag in entities:
            name=gmsh.model.getEntityName(dim,tag);b=gmsh.model.getBoundingBox(dim,tag)
            records.append({'name':name,'bounds_step_mm':list(b),'volume_mm3':gmsh.model.occ.getMass(dim,tag)})
            if name.endswith('_PCB'):groups['pcb'].append((dim,tag))
            elif name.endswith(('_copper','_pad','_via','_track')):groups['copper'].append((dim,tag))
            else:groups['resistors'].append((dim,tag))
            for ref in refs:
                if '/'+ref+'/' in name and 'substrate' in name.lower():
                    positions[ref]=[(b[0]+b[3])/2,-(b[1]+b[4])/2]
        if not groups['pcb']:raise WorkflowError('Cannot identify the PCB solid in the KiCad STEP export')
        bounds=[gmsh.model.getBoundingBox(*e) for e in groups['pcb']]
        xy=[min(b[0] for b in bounds),-max(b[4] for b in bounds),max(b[3] for b in bounds),-min(b[1] for b in bounds)]
        xy_error=max(abs(a-b) for a,b in zip(xy,outline.bounds))
        if xy_error>max(board['polygon_chord_error_mm'],.001):raise WorkflowError('STEP XY outline does not align with the saved board')
        # KiCad excludes outer copper from its board dielectric STEP body.
        z_error=max(abs(min(b[2] for b in bounds)),abs(max(b[5] for b in bounds)-(offset+copper[0]['z_bottom_mm'])))
        if z_error>.001:raise WorkflowError('STEP board thickness/Z origin does not match the saved physical stackup')
        comps={c['ref']:c for c in board['components']}
        placement={ref:math.dist(p,comps[ref]['position']) for ref,p in positions.items()}
        if any(e>.01 for e in placement.values()):raise WorkflowError('Resistor STEP placement does not match the saved footprint')
        transform=[1,0,0,0,0,-1,0,0,0,0,1,-offset,0,0,0,1]
        gmsh.model.occ.affineTransform(entities,transform);gmsh.model.occ.synchronize()
        gmsh.option.setNumber('Geometry.OCCExportOnlyVisible',1)
        for name,parts in groups.items():
            if not parts:continue
            gmsh.model.setVisibility(gmsh.model.getEntities(),0,recursive=True)
            gmsh.model.setVisibility(parts,1,recursive=True)
            gmsh.write(str(directory/(name+'-thermal-coordinates.step')))
        result={'units':'mm','step_to_thermal_matrix_row_major':transform,'outline_error_mm':xy_error,
                'board_z_error_mm':z_error,'verified_package_centres_error_mm':placement,
                'packages_without_named_centre_check':sorted(set(refs)-set(placement)),
                'package_note':'Original CAD package standoff is preserved; constructed FEM solder/body thickness is a separate editable assumption.',
                'solids':records,'alignment_pass':True}
        write_json(directory/'step-audit.json',result)
        return result
    finally:gmsh.finalize()
