"""Reopen native files in authenticated container GUIs on a private X display.

Run after the layered-via example. Requires Xvfb, xauth, xwd, Pillow, xdotool.
Use --tool to check one application. No desktop-wide X access is enabled.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import uuid
from PIL import Image
import numpy as np
from pcb_thermal.common import ROOT, CACHE, WorkflowError, digest, write_json
from pcb_thermal.runtime import Runtime

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--tool',choices=['kicad','gmsh','freecad','elmer','paraview','all'],default='all')
a=p.parse_args()
CACHE.mkdir(exist_ok=True)
workflow_lock=(CACHE/'workflow.lock').open('a')
print('Waiting for exclusive thermal workflow access before GUI tests',flush=True)
fcntl.flock(workflow_lock,fcntl.LOCK_EX)
example=ROOT/'results/examples/layered-via'
out=ROOT/'results/validation/gui-reopen';out.mkdir(parents=True,exist_ok=True)
xd=shutil.which('xdotool') or ROOT/'.cache/gui-test-root/usr/bin/xdotool'
if not Path(xd).is_file():
    raise SystemExit('Install xdotool to run this optional GUI verification')
display=next(n for n in range(192,220) if not Path(f'/tmp/.X11-unix/X{n}').exists())
auth=out/'xauthority';auth.touch(mode=0o600)
env=dict(os.environ,DISPLAY=f':{display}',XAUTHORITY=str(auth),
         LD_LIBRARY_PATH=str(ROOT/'.cache/gui-test-root/usr/lib/x86_64-linux-gnu'))
os.environ.update(DISPLAY=env['DISPLAY'],XAUTHORITY=env['XAUTHORITY'])
subprocess.run(['xauth','-f',str(auth),'add',env['DISPLAY'],'MIT-MAGIC-COOKIE-1',os.urandom(16).hex()],env=env,check=True)
xvfb=subprocess.Popen(['Xvfb',env['DISPLAY'],'-screen','0','1280x900x24','-extension','MIT-SHM','-auth',str(auth)],env=env,
                      stdout=subprocess.DEVNULL,stderr=(out/'xvfb.log').open('w'))
wm=None
openbox=shutil.which('openbox') or ROOT/'.cache/gui-test-root/usr/bin/openbox'
if Path(openbox).is_file():
    time.sleep(1)
    wm_home=out/'window-manager-home';wm_home.mkdir(exist_ok=True)
    wm_env=dict(env,HOME=str(wm_home),XDG_CONFIG_HOME=str(wm_home/'.config'),
                XDG_CACHE_HOME=str(wm_home/'.cache'),
                XDG_DATA_DIRS=str(ROOT/'.cache/gui-test-root/usr/share')+':/usr/local/share:/usr/share')
    wm=subprocess.Popen([str(openbox),'--sm-disable'],env=wm_env,
                        stdout=subprocess.DEVNULL,stderr=(out/'openbox.log').open('w'))

def xdo(*args):
    return subprocess.check_output([str(xd),*args],env=env,text=True,timeout=10,stderr=subprocess.DEVNULL).strip()

def windows(pattern):
    try:return xdo('search','--onlyvisible','--name',pattern).splitlines()
    except subprocess.CalledProcessError:return []

def snapshot(label):
    raw=out/(label+'.xwd')
    subprocess.run(['xwd','-display',env['DISPLAY'],'-root','-silent','-out',str(raw)],env=env,check=True)
    data=raw.read_bytes();h=struct.unpack('>25I',data[:100])
    if h[7]!=0 or h[11] not in (24,32):raise WorkflowError('Unexpected XWD pixel format')
    im=Image.frombytes('RGB',(h[4],h[5]),data[h[0]+h[19]*12:],'raw','BGR' if h[11]==24 else 'BGRX',h[12])
    im.save(out/(label+'.png'));return im

# KiCad may create project preferences beside the board. Use a disposable copy;
# hash both the copy and the original so reopening never changes design sources.
kicad_work=out/'kicad-project';kicad_work.mkdir(exist_ok=True)
shutil.copy2(ROOT/'examples/layered-via/board.kicad_pcb',kicad_work/'board.kicad_pcb')
specs=[('kicad',kicad_work,['pcbnew','/work/board.kicad_pcb'],'PCB Editor'),
       ('gmsh',example/'mesh',['gmsh','/work/board.msh'],'Gmsh'),
       ('freecad',example/'extract',['freecad','/work/board.step'],'FreeCAD'),
       ('elmer',example,['ElmerGUI'],'ElmerGUI'),
       ('paraview',example,['paraview','--state=/work/postprocess/view.pvsm'],'ParaView')]
checks={}
if (out/'checks.json').exists():checks=json.loads((out/'checks.json').read_text())
try:
    time.sleep(1)
    for label,work,command,pattern in specs:
        if a.tool not in (label,'all'):continue
        originals={str(f):digest(f) for f in [example/'solve/case.sif',example/'solve/mesh/case.sif',example/'extract/board.step',
                                            ROOT/'examples/layered-via/board.kicad_pcb',kicad_work/'board.kicad_pcb']}
        name='pcb-thermal-gui-test-'+uuid.uuid4().hex[:12]
        rt=Runtime();base=rt.base;rt.base=lambda *args,**kw:base(*args,**kw)+['--name',name]
        with ThreadPoolExecutor(max_workers=1) as pool:
            task=pool.submit(rt.run,'tools',command,output=work,gui=True,log=out/(label+'.log'))
            try:
                win=None
                for _ in range(90):
                    found=windows(pattern)
                    if found:win=found[0];break
                    if task.done():task.result()
                    time.sleep(1)
                if not win:raise WorkflowError(label+' did not create a visible window')
                # Xvfb has no window manager: focusing the main window before
                # closing this modal dialog can hide it and block state loading.
                time.sleep(4)
                if label=='kicad':
                    for dialog in windows('KiCad Setup'):
                        xdo('windowraise',dialog);xdo('windowfocus',dialog)
                        time.sleep(.5);snapshot('kicad-setup')
                        # KiCad's supported cancel/confirm path applies and saves
                        # defaults (startwizard.cpp, 10.0.7), without importing
                        # a previous user profile into this test.
                        xdo('key','Escape');time.sleep(1);xdo('key','Return');time.sleep(4)
                    # A fresh KiCad profile asks how to initialize its installed
                    # footprint table. Accept the default table in this test profile.
                    for dialog in windows('Configure Global Footprint Library Table'):
                        xdo('windowfocus',dialog);xdo('key','Return');time.sleep(3)
                    print('KiCad visible windows: '+str([xdo('getwindowname',w) for w in windows('.*')]),flush=True)
                    found=windows('board.*PCB Editor')
                    if found:win=found[0]
                for dialog in windows('Welcome'):
                    xdo('windowfocus',dialog);xdo('key','Escape')
                xdo('windowsize',win,'1200','850');xdo('windowfocus',win)
                if label=='kicad':
                    xdo('key','Home')
                elif label=='freecad':
                    # Select the imported document, not the first-run Start tab.
                    xdo('key','alt+w');time.sleep(.4);xdo('key','1');time.sleep(.4)
                    xdo('key','0','v','f')
                elif label=='elmer':
                    xdo('key','alt+f');time.sleep(.3);xdo('key','p');time.sleep(.8)
                    xdo('key','ctrl+l');xdo('type','--clearmodifiers','/work/solve/mesh')
                    xdo('key','Return');time.sleep(.6);xdo('key','Return')
                time.sleep(6)
                title=xdo('getwindowname',win);im=snapshot(label)
                check={'visible_window':title,'authenticated_display':True,'image':label+'.png'}
                if label=='paraview':
                    pixels=np.asarray(im)[240:780,350:1150].astype(int)
                    colored=(pixels.max(axis=2)-pixels.min(axis=2)>40)
                    check['colored_viewport_fraction']=float(colored.mean())
                    if colored.mean()<.05:raise WorkflowError('ParaView viewport does not display the thermal model')
                if label=='elmer' and '/work/solve/mesh' not in title:
                    raise WorkflowError('ElmerGUI did not reopen the generated project')
                if label=='kicad' and 'board' not in title:
                    raise WorkflowError('KiCad did not reopen the copied board')
                check['input_files_preserved']=all(digest(f)==h for f,h in originals.items())
                if not check['input_files_preserved']:raise WorkflowError('GUI reopening modified an input file')
                check['pass']=True;checks[label]=check;write_json(out/'checks.json',checks)
                print(label+': reopened; source hashes unchanged',flush=True)
            except BaseException as error:
                checks[label]={'pass':False,'error':str(error)};write_json(out/'checks.json',checks);raise
            finally:
                subprocess.run([rt.engine,'stop','-t','2',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:task.result(timeout=15)
                except WorkflowError:pass  # Intentional closure of this test's container.
finally:
    if wm:wm.terminate();wm.wait(timeout=10)
    xvfb.terminate();xvfb.wait(timeout=10)
