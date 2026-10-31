"""Public file-based thermal workflow commands."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from .common import ROOT,WorkflowError,call,positive,write_json

def parser():
    p=argparse.ArgumentParser(prog='pcb-thermal',description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('bootstrap');b.add_argument('--cuda',action='store_true')
    b=sub.add_parser('build');b.add_argument('--profile',choices=['cpu','tools','cuda','all'],default='cpu');b.add_argument('--jobs',type=positive,default=2);b.add_argument('--cuda-arch',default='75');b.add_argument('--cuda-version',default='12.9.1')
    d=sub.add_parser('doctor');d.add_argument('--backend',choices=['cpu','cuda','auto'],default='cpu');d.add_argument('--full',action='store_true')
    r=sub.add_parser('run');r.add_argument('case',type=Path);r.add_argument('--stage',choices=['extract','mesh','convert','solve','postprocess','all'],default='all');r.add_argument('--force',action='store_true');r.add_argument('--backend',choices=['cpu','cuda','auto']);r.add_argument('--mpi-ranks',type=positive);r.add_argument('--threads-per-rank',type=positive);r.add_argument('--gpu-count',type=positive);r.add_argument('--sif',type=Path)
    s=sub.add_parser('sweep');s.add_argument('case',type=Path);s.add_argument('--parameter',required=True);s.add_argument('--values',nargs='+',required=True);s.add_argument('--backend',choices=['cpu','cuda','auto'],default='cpu')
    s=sub.add_parser('study');s.add_argument('case',type=Path);s.add_argument('--section',choices=['steady','mesh','detail','crop','transient','all'],default='steady');s.add_argument('--schedules',nargs='+',choices=['automatic','odd','even']);s.add_argument('--time-budget-minutes',type=float);s.add_argument('--detail-check',action='store_true',help='If at least 25 minutes remain, allow one 20-minute automatic h=10 detail-margin check')
    s.add_argument('--first-case-minutes',type=float,default=20,help='Shorten the first-case allowance (maximum/default: 20 minutes)')
    g=sub.add_parser('gui');g.add_argument('tool',choices=['kicad','pcbnew','freecad','gmsh','elmer','paraview']);g.add_argument('--workdir',type=Path,required=True);g.add_argument('args',nargs='*')
    for name in ('export','import'):
        t=sub.add_parser(name);t.add_argument('directory',type=Path)
        if name=='export':t.add_argument('--profile',choices=['cpu','cuda','all'],default='cpu')
    return p

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv);extra=[]
    if argv and argv[0]=='gui' and '--' in argv:
        i=argv.index('--');extra=argv[i+1:];argv=argv[:i]
    a=parser().parse_args(argv)
    try:
        if a.command=='bootstrap':
            call(['bash',ROOT/'scripts/bootstrap-host.sh'])
            if a.cuda:call(['sudo','bash',ROOT/'scripts/bootstrap-nvidia.sh'])
        elif a.command=='build':
            from .build import build
            build(a.profile,a.jobs,a.cuda_arch,a.cuda_version)
        elif a.command=='run':
            from .pipeline import run
            out=run(a.case,a.stage,a.force,a.backend,a.mpi_ranks,a.threads_per_rank,a.gpu_count,a.sif);print(out)
        elif a.command=='doctor':
            from .validation import doctor
            return doctor(a.backend,a.full)
        elif a.command=='sweep':
            from .sweep import sweep
            sweep(a.case,a.parameter,a.values,a.backend)
        elif a.command=='study':
            from .study_runner import study
            return study(a.case,a.section,a.schedules,a.time_budget_minutes,a.detail_check,a.first_case_minutes)
        elif a.command=='gui':
            from .runtime import Runtime
            tool={'elmer':'ElmerGUI'}.get(a.tool,a.tool)
            Runtime().run('tools',[tool]+a.args+extra,output=a.workdir,gui=True)
        elif a.command in ('export','import'):
            from .build import transfer
            transfer(a.directory,a.profile if a.command=='export' else None)
        return 0
    except (WorkflowError,OSError,ValueError,KeyError) as e:
        print('pcb-thermal: '+str(e),file=sys.stderr);return 1
    except KeyboardInterrupt:
        print('Interrupted; successful stages and logs are retained.',file=sys.stderr);return 130

if __name__=='__main__':raise SystemExit(main())
