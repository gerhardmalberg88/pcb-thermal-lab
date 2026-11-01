#!/usr/bin/env python3
"""Parametric study sections for explicitly requested work, with resumable evidence."""
import argparse,copy,json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pcb_thermal.config import load
from pcb_thermal.pipeline import run
from pcb_thermal.common import write_json,WorkflowError
from pcb_thermal.study import compare_runs,write_study_report
p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);p.add_argument('--section',choices=['steady','mesh','detail','crop','transient','all'],default='all');a=p.parse_args()
source,base,project,board,baseout=load(a.case);root=baseout.parent;configdir=root/'study-inputs';configdir.mkdir(parents=True,exist_ok=True)
records=[];acceptance={};manifest=root/('study-'+a.section+'.json')
def interrupted(signum,frame):raise KeyboardInterrupt('Study interrupted by signal '+str(signum))
signal.signal(signal.SIGTERM,interrupted)
def execute(label,changes):
 c=copy.deepcopy(base)
 c['execution'].setdefault('max_memory_gib',8.0)
 for key,value in changes.items():
  obj=c;parts=key.split('.')
  for part in parts[:-1]:obj=obj.setdefault(part,{})
  obj[parts[-1]]=value
 c.update(project_root=str(project),board=str(board),output=str(root/label),name=label)
 path=configdir/(label+'.json');write_json(path,c)
 write_json(manifest,{'status':'running','active':label,'completed':records,'started_unix':start})
 result=run(path,backend='cpu');summary=json.loads((result/'postprocess/summary.json').read_text())
 records.append({'case':label,'path':str(result),'summary':summary});write_json(manifest,{'status':'running','completed':records,'started_unix':start})
 write_study_report(root,a.section,records,'running',acceptance)
 return summary

def convergence(label,values):
 series=records[-len(values):]
 result=compare_runs(series[-2]['path'],series[-1]['path'])
 result['last_pair_pass']=result['pass']
 result['comparisons_to_finest']=[compare_runs(r['path'],series[-1]['path']) for r in series[:-1]]
 # The initial study uses mesh scale 1 and a 10 mm detail margin. Convergence
 # of two finer models alone does not validate those production settings.
 if label in ('mesh','detail'):
  baseline_index=1 if label=='mesh' else 0
  result['production_baseline_check']=compare_runs(series[baseline_index]['path'],series[-1]['path'])
  result['pass']=result['pass'] and result['production_baseline_check']['pass']
 result['completed_resolutions']=len(values)
 acceptance[label]=result
 write_json(root/(label+'-convergence.json'),result);return result['last_pair_pass']

start=time.time()
try:
 if a.section in ('steady','all'):
  for schedule in ['automatic','odd','even']:
   for h in [10,5,20,50]:execute(f'{schedule}-h{h}',{'sources.schedule':schedule,'cooling.h_w_m2k':h})
 if a.section in ('mesh','all'):
  values=[execute('mesh-'+str(scale),{'mesh.scale':scale}) for scale in [1.5,1,.75]]
  for scale in [.5,.375]:
   if convergence('mesh',values):break
   values.append(execute('mesh-'+str(scale),{'mesh.scale':scale}))
  convergence('mesh',values)
 if a.section in ('detail','all'):
  values=[execute('detail-'+str(margin),{'geometry.detail_margin_mm':margin}) for margin in [10,20,30]]
  convergence('detail',values)
 if a.section in ('crop','all'):
  from pcb_thermal.geometry import prepare
  from pcb_thermal.power import derive
  b=json.loads((baseout/'extract/board.json').read_text());g=prepare(b,base)
  shapes=list(g['resistors'].values());bounds=[r['body'].bounds for r in shapes]
  limits=[min(x[0] for x in bounds),min(x[1] for x in bounds),max(x[2] for x in bounds),max(x[3] for x in bounds)]
  values=[]
  for margin in [5,10,20]:
   crop=[limits[0]-margin,limits[1]-margin,limits[2]+margin,limits[3]+margin]
   # Shift only artificial cuts outward until no drill is bisected.
   for _ in range(100):
    changed=False
    for hole in b['holes']:
     for axis in [0,1]:
      radius=max(hole['drill'])/2+.05;center=hole['center'][axis]
      if center-radius<crop[axis]<center+radius:crop[axis]=center-radius;changed=True
      if center-radius<crop[axis+2]<center+radius:crop[axis+2]=center+radius;changed=True
    if not changed:break
   values.append(execute('crop-'+str(margin),{'geometry.mode':'crop','geometry.crop_mm':crop}))
  values.append(execute('explicit-whole-board',{'geometry.mode':'explicit'}));convergence('crop',values)
 if a.section in ('transient','all'):
  values=[execute('transient-dt'+str(dt),{'analysis':'transient','transient.on_s':1800,'transient.off_s':1800,'transient.step_s':dt,'transient.field_interval_s':5}) for dt in [1,.5]]
  convergence('timestep',values)
 status='complete' if all(v['pass'] for v in acceptance.values()) else 'unconverged'
 write_json(manifest,{'status':status,'completed':records,'convergence':acceptance,'started_unix':start,'wall_seconds':time.time()-start})
 write_study_report(root,a.section,records,status,acceptance)
except BaseException as error:
 write_json(manifest,{'status':'failed','error':str(error),'completed':records,'started_unix':start})
 write_study_report(root,a.section,records,'failed: '+str(error),acceptance);raise
