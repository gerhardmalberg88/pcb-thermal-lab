"""Run with ParaView's pvpython, never the numerical/pcbnew interpreter."""
import json
import csv
import sys
from pathlib import Path
from paraview.simple import *

root=Path(sys.argv[1]).resolve();out=root/'postprocess';out.mkdir(exist_ok=True)
files=sorted((root/'solve').rglob('temperature*.pvtu')) or sorted((root/'solve').rglob('temperature*.vtu'))
if not files:raise RuntimeError('Elmer field files are missing')
collection=next(iter((root/'solve').rglob('temperature.pvd')),None)
if collection:reader=PVDReader(FileName=str(collection))
else:reader=XMLPartitionedUnstructuredGridReader(FileName=[str(f) for f in files]) if files[0].suffix=='.pvtu' else XMLUnstructuredGridReader(FileName=[str(f) for f in files])
reader.UpdatePipeline();scene=GetAnimationScene();scene.UpdateAnimationUsingDataTimeSteps()
summary=json.loads((out/'summary.json').read_text());case=json.loads((root/'case.resolved.json').read_text())
# Alternating channels can peak before the final heating step. Select the hottest
# available field using the independently retained scalar history.
render_info={'selection':'final steady field'}
if case['analysis']=='transient':
    with (out/'history.csv').open() as stream:history=list(csv.DictReader(stream))
    saved=list(reader.TimestepValues)
    candidates=[]
    for row in history:
        t=float(row['time_s'])
        if any(abs(t-float(frame))<1e-8 for frame in saved):
            candidates.append((float(row['temperature_max_k']),t))
    if not candidates:raise RuntimeError('Saved field times do not match the scalar history')
    peak,selected_time=max(candidates)
    scene.AnimationTime=selected_time
    render_info.update(selection='hottest saved field from scalar history',
                       saved_field_maximum_c=peak-273.15,
                       all_steps_maximum_c=summary['maximum_temperature_c'])
else:scene.GoToLast()
render_info['field_time_s']=float(scene.AnimationTime)
(out/'render.json').write_text(json.dumps(render_info,indent=2)+'\n')
reader.UpdatePipeline(scene.AnimationTime)
temperature=next((x for x in reader.PointData.keys() if x.lower()=='temperature'),None)
if temperature is None:raise RuntimeError('Temperature field missing')
calc=Calculator(Input=reader);calc.ResultArrayName='Temperature_C';calc.Function=f'{temperature} - 273.15'
view=CreateView('RenderView');view.ViewSize=[1500,1000];view.OrientationAxesVisibility=1
layout=CreateLayout(name='Thermal results');AssignViewToLayout(view=view,layout=layout,hint=0);SetActiveView(view)
view.Background=[1,1,1];view.UseColorPaletteForBackground=0
display=Show(calc,view);ColorBy(display,('POINTS','Temperature_C'));display.SetScalarBarVisibility(view,True)
lut=GetColorTransferFunction('Temperature_C');lut.ApplyPreset('Inferno (matplotlib)',True)
lut.RescaleTransferFunction(case['cooling']['ambient_c'],summary['maximum_temperature_c'])
bar=GetScalarBar(lut,view);bar.Title='Temperature (°C)';bar.ComponentTitle='';bar.TitleColor=[0.1,0.1,0.1];bar.LabelColor=[0.1,0.1,0.1]
annotation=Text();annotation.Text=f'{case.get("name","PCB thermal")} | resistor heat {summary["resistor_heat_w"]:.3f} W\nAmbient {case["cooling"]["ambient_c"]} °C | h = {case["cooling"]["h_w_m2k"]} W/m²K'
if case['analysis']=='transient':annotation.Text+=f' | t = {scene.AnimationTime:g} s'
ad=Show(annotation,view);ad.Color=[.1,.1,.1];ad.FontSize=14;ad.WindowLocation='Upper Left Corner'
calc.UpdatePipeline(scene.AnimationTime);bounds=calc.GetDataInformation().GetBounds();center=[(bounds[2*i]+bounds[2*i+1])/2 for i in range(3)];span=max(bounds[1]-bounds[0],bounds[3]-bounds[2]);view.CameraParallelProjection=1
# Samples are in PCB material beneath footprint/pad positions, never inside an
# omitted package. Invalid points (e.g. an open drill) remain explicitly absent.
import vtk
board=json.loads((root/'extract/board.json').read_text())
points=vtk.vtkPoints();points.SetDataTypeToDouble();samples=[]
back=min(l['z_bottom_mm'] for l in board['stackup'] if l['kind']=='copper')+.001
for component in board['components']:
    z=back if component['flipped'] else -.001
    locations=[('footprint-centre',component['position'])]+[('pad-'+p['number'],p['position']) for p in component['pads']]
    for label,(x,y) in locations:
        points.InsertNextPoint(x*.001,y*.001,z*.001)
        samples.append([component['ref'],label,x,y,z])
poly=vtk.vtkPolyData();poly.SetPoints(points)
probe=vtk.vtkCompositeDataProbeFilter();probe.SetInputData(poly);probe.SetSourceData(servermanager.Fetch(calc));probe.Update()
data=probe.GetOutput().GetPointData();valid=data.GetArray('vtkValidPointMask');temperatures=data.GetArray('Temperature_C')
with (out/'nearby-board-temperatures.csv').open('w') as stream:
    writer=csv.writer(stream);writer.writerow(['reference','sample','x_mm','y_mm','z_mm','board_temperature_c','valid','field_time_s'])
    for i,row in enumerate(samples):
        ok=bool(valid.GetValue(i));writer.writerow(row+[temperatures.GetValue(i) if ok else '',ok,scene.AnimationTime])
for name,offset,up in [('top',[0,0,3],[0,-1,0]),('bottom',[0,0,-3],[0,-1,0]),('isometric',[2,-2,3],[0,0,1])]:
    view.CameraPosition=[center[i]+offset[i]*span for i in range(3)];view.CameraFocalPoint=center;view.CameraViewUp=up;ResetCamera(view)
    SaveScreenshot(str(out/(name+'.png')),view,ImageResolution=[1500,1000])
slice_=Slice(Input=calc);slice_.SliceType='Plane';slice_.SliceType.Origin=center;slice_.SliceType.Normal=[0,1,0]
Hide(calc,view);sd=Show(slice_,view);ColorBy(sd,('POINTS','Temperature_C'))
view.CameraPosition=[center[0],center[1]-3*span,center[2]];view.CameraFocalPoint=center;view.CameraViewUp=[0,0,1];ResetCamera(view)
SaveScreenshot(str(out/'cross-section.png'),view,ImageResolution=[1500,1000])
Hide(slice_,view);Show(calc,view);view.CameraPosition=[center[0]+2*span,center[1]-2*span,center[2]+3*span];view.CameraFocalPoint=center;view.CameraViewUp=[0,0,1];ResetCamera(view)
SaveState(str(out/'view.pvsm'))
# A portable loading script relocates reader filenames before rendering the state.
(out/'open-view.py').write_text('from pathlib import Path\nfrom paraview.simple import *\np=Path(globals().get("__file__","postprocess/open-view.py")).resolve().parent\nLoadState(str(p/"view.pvsm"),data_directory=str(p.parent/"solve/mesh"),restrict_to_data_directory=True)\nRenderAllViews()\n')
print('Rendered top/bottom/isometric/section views and saved ParaView state')
