"""Separate mechanical STEP inputs for straight-sided extruded cooling parts.

Prismatic parts use the same planar arrangement as the PCB and therefore share
interface nodes. Unsupported curved/non-prismatic solids are rejected, never
silently substituted by bounding boxes. STEP units are converted by OpenCASCADE
to millimetres; placement uses the documented thermal coordinate system.
"""
import math
from pathlib import Path
import numpy as np
from .common import WorkflowError

def load_parts(case, project):
    import gmsh
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.affinity import rotate,translate
    result=[]
    for item in case.get('mechanicals',[]):
        path=(Path(project)/item['step']).resolve()
        if not path.is_relative_to(Path(project).resolve()) or not path.is_file():
            raise WorkflowError('Mechanical STEP must exist within project_root')
        gmsh.initialize()
        try:
            gmsh.option.setNumber('General.Terminal',0)
            solids=gmsh.model.occ.importShapes(str(path));gmsh.model.occ.synchronize()
            solids=[s for s in solids if s[0]==3]
            if len(solids)!=1:raise WorkflowError('Each mechanical STEP must contain exactly one connected prismatic solid')
            surfaces=gmsh.model.getBoundary(solids,oriented=False)
            flat=[];bottom=[];top=[];zmin=math.inf;zmax=-math.inf
            for dim,tag in surfaces:
                if gmsh.model.getType(dim,tag)!='Plane':raise WorkflowError('Mechanical STEP currently supports planar, straight-sided prisms only')
                edges=gmsh.model.getBoundary([(dim,tag)],oriented=False)
                lines=[]
                for edim,edge in edges:
                    if gmsh.model.getType(edim,edge)!='Line':raise WorkflowError('Mechanical STEP edges must be straight')
                    ends=gmsh.model.getBoundary([(edim,edge)],oriented=False)
                    coords=[gmsh.model.getValue(0,p,[]).tolist() for _,p in ends]
                    if len(coords)!=2:raise WorkflowError('Invalid mechanical STEP edge')
                    lines.append(coords)
                points=np.asarray(lines).reshape(-1,3);zmin=min(zmin,points[:,2].min());zmax=max(zmax,points[:,2].max())
                if np.ptp(points[:,2])<1e-7:
                    # Assemble each closed polygon loop from the exact STEP vertices.
                    remaining=[(tuple(a[:2]),tuple(b[:2])) for a,b in lines];rings=[]
                    while remaining:
                        a,b=remaining.pop();ring=[a,b]
                        while np.linalg.norm(np.array(ring[-1])-ring[0])>1e-7:
                            found=False
                            for index,(c,d) in enumerate(remaining):
                                if np.linalg.norm(np.array(c)-ring[-1])<1e-7:next_=d
                                elif np.linalg.norm(np.array(d)-ring[-1])<1e-7:next_=c
                                else:continue
                                ring.append(next_);remaining.pop(index);found=True;break
                            if not found:raise WorkflowError('Mechanical face loop does not close')
                        rings.append(Polygon(ring))
                    shape=Polygon()
                    for r in rings:shape=shape.symmetric_difference(r)
                    flat.append((float(points[0,2]),shape))
                else:
                    # A side plane must have a horizontal normal (vertical wall).
                    normal=np.cross(points[1]-points[0],points[2]-points[0])
                    # Duplicate edge vertices can be collinear; use all triples.
                    for p in points[2:]:
                        normal=np.cross(points[1]-points[0],p-points[0])
                        if np.linalg.norm(normal)>1e-10:break
                    if abs(normal[2])>1e-7*max(np.linalg.norm(normal),1e-30):
                        raise WorkflowError('Sloped mechanical STEP walls require a general tetrahedral contact model')
            low=unary_union([g for z,g in flat if abs(z-zmin)<1e-7]);high=unary_union([g for z,g in flat if abs(z-zmax)<1e-7])
            height=zmax-zmin;volume=gmsh.model.occ.getMass(*solids[0])
            if low.is_empty or low.symmetric_difference(high).area>1e-6 or abs(volume-low.area*height)>max(volume*1e-7,1e-7):
                raise WorkflowError('Mechanical STEP must be a constant-section vertical prism')
            offset=item.get('translate_mm',[0,0,0]);angle=float(item.get('rotate_z_deg',0))
            shape=translate(rotate(low,angle,origin=(0,0)),*offset[:2])
            bottom=zmin+offset[2];top=zmax+offset[2]
            contact=item.get('contact',{'kind':'perfect'})
            if contact['kind']=='layer':
                t=float(contact['thickness_mm'])
                if t<=0:raise WorkflowError('Contact thickness must be positive')
                interface=(bottom-t,bottom)
            elif contact['kind']=='perfect':interface=None
            else:raise WorkflowError('Mechanical contact.kind must be perfect or layer')
            if item['material'] not in case['materials']:raise WorkflowError('Unknown mechanical material')
            if interface and contact['material'] not in case['materials']:raise WorkflowError('Unknown contact material')
            result.append({'name':item['name'],'shape':shape,'z_bottom_mm':bottom,'z_top_mm':top,
                           'material':item['material'],'contact':contact,'interface':interface,
                           'source':str(path),'volume_mm3':volume})
        finally:gmsh.finalize()
    return result
