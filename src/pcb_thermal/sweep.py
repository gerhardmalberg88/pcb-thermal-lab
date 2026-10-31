"""Sequential studies reuse geometry while preserving individual case evidence."""
import copy
import json
from pathlib import Path
from .common import write_json
from .config import load
from .pipeline import run
from .study import compare_runs

def sweep(path,parameter,values,backend='cpu'):
    path,case,project,board,out=load(path);study=out/'sweeps'/parameter.replace('.','-');study.mkdir(parents=True,exist_ok=True)
    rows=[];completed=[]
    for value in values:
        c=copy.deepcopy(case)
        try:value=json.loads(value) if isinstance(value,str) else value
        except json.JSONDecodeError:pass
        target=c;keys=parameter.split('.')
        for key in keys[:-1]:target=target[key]
        target[keys[-1]]=value
        c.update(project_root=str(project),board=str(board),output=str(study/str(value)),name=f'{case.get("name","case")}: {parameter}={value}')
        config=study/(str(value)+'.yaml');write_json(config,c)
        result=run(config,backend=backend)
        completed.append(result)
        rows.append({'value':value,**json.loads((result/'postprocess/summary.json').read_text())})
        write_json(study/'study.json',{'parameter':parameter,'cases':rows})
    if parameter in ('mesh.scale','geometry.detail_margin_mm','transient.step_s') and len(rows)>1:
        write_json(study/'convergence.json',compare_runs(completed[-2],completed[-1]))
    return study
