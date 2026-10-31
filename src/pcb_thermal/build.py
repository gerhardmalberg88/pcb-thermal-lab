"""Pinned, resumable container builds and offline image transfer."""
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from .common import ROOT,CACHE,WorkflowError,call,digest,write_json
from .runtime import Runtime,IMAGES

def fetch(name,asset):
    target=CACHE/'upstream'/name;target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and digest(target)==asset['sha256']:return target
    temp=target.with_suffix('.download')
    with urllib.request.urlopen(asset['url'],timeout=120) as src,temp.open('wb') as dst:shutil.copyfileobj(src,dst)
    if digest(temp)!=asset['sha256']:raise WorkflowError(f'Checksum mismatch: {name}; retained {temp}')
    temp.replace(target);return target

def build(profile='cpu',jobs=2,cuda_arch='75',cuda_version='12.9.1'):
    rt=Runtime()
    if shutil.disk_usage(ROOT).free<8*1024**3:raise WorkflowError('Image builds require at least 8 GiB free before starting')
    if rt.engine=='native':
        call(['bash',ROOT/'scripts/build-native.sh'],env={**os.environ,'BUILD_JOBS':str(jobs)})
        return
    pins=json.loads((ROOT/'env/pins.json').read_text());ctx=CACHE/'build-context';ctx.mkdir(parents=True,exist_ok=True)
    if profile in ('cpu','tools','all') or not rt.image_exists('cpu'):
        for dst,key in [('elmer.tar.gz','elmer-26.1.tar.gz'),('FreeCAD.AppImage','FreeCAD.AppImage'),('cacert.pem','cacert.pem')]:
            source=fetch(key,pins['assets'][key]);target=ctx/dst
            if target.exists():target.unlink()
            os.link(source,target)
        call([rt.engine,'build','--layers','--build-arg','BASE_IMAGE='+pins['base_image'],
              '--build-arg','APT_SNAPSHOT='+pins['ubuntu_snapshot'],'--build-arg',f'BUILD_JOBS={jobs}',
              '-t',IMAGES['cpu'],'-f',ROOT/'containers/Containerfile.cpu',ctx],log=CACHE/'logs/build-cpu.log')
        for kind in ('cpu',):
            out=ROOT/'env/locks'/kind;out.mkdir(parents=True,exist_ok=True)
            write_json(out/'image.json',{'id':rt.image_id(kind),'name':IMAGES[kind],'pins':pins})
            inventory=rt.run(kind,['cat','/opt/provenance/apt-packages.txt'],capture=True).stdout
            (out/'apt-packages.txt').write_text(inventory)
    if profile in ('cpu','tools','all') or not rt.image_exists('tools'):
        source=fetch('ParaView-5.13.3.tar.gz',pins['assets']['ParaView-5.13.3.tar.gz']);target=ctx/'paraview.tar.gz'
        if target.exists():target.unlink()
        os.link(source,target)
        call([rt.engine,'build','--layers','--build-arg','CPU_IMAGE='+IMAGES['cpu'],
              '-t',IMAGES['tools'],'-f',ROOT/'containers/Containerfile.tools',ctx],log=CACHE/'logs/build-tools.log')
        out=ROOT/'env/locks/tools';out.mkdir(parents=True,exist_ok=True)
        write_json(out/'image.json',{'id':rt.image_id('tools'),'name':IMAGES['tools'],'pins':pins})
    if profile in ('cuda','all'):
        from .cuda import build_cuda
        build_cuda(rt,pins,ctx,jobs,cuda_arch,cuda_version)

def transfer(directory,profile=None):
    rt=Runtime();directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    if rt.engine=='native':raise WorkflowError('Image transfer requires Podman or Docker')
    if profile:
        kinds=['tools','cpu']+(['cuda'] if profile in ('all','cuda') else [])
        identities={kind:rt.image_id(kind) for kind in kinds}
        previous=directory/'images.json'
        old={}
        if previous.exists():
            old=json.loads(previous.read_text())
            hashes={name:digest(directory/name) for name in {item['file'] for item in old.values()}
                    if Path(name).name==name and (directory/name).is_file()}
            if set(old)==set(kinds) and all(old[k]['id']==identities[k] and hashes.get(old[k]['file'])==old[k]['sha256'] for k in kinds):
                print('Image archive already matches the selected images');return
        file='pcb-thermal-images.tar'
        target=directory/file
        if target.exists() and (target.is_symlink() or not old or
                any(item.get('file')!=file or item.get('sha256')!=hashes.get(file) for item in old.values())):
            raise WorkflowError('Existing archive is not owned by the matching images.json; choose another export directory')
        inspected=json.loads(call([rt.engine,'image','inspect',*[IMAGES[k] for k in kinds]],capture=True).stdout)
        # Sum is deliberately conservative: shared layers normally make the
        # archive smaller. Keep the old valid archive until replacement succeeds.
        budget=sum(item['Size'] for item in inspected)+2*1024**3
        if shutil.disk_usage(directory).free<budget:
            raise WorkflowError(f'Export needs up to {budget/1024**3:.1f} GiB additional temporary space')
        flags=['--multi-image-archive','--format','docker-archive'] if rt.engine=='podman' else []
        # Podman cannot update an existing docker archive. Export to an owned
        # temporary directory, hash it, then atomically replace the old archive.
        with tempfile.TemporaryDirectory(prefix='.pcb-thermal-export-',dir=directory) as temporary:
            pending=Path(temporary)/file
            call([rt.engine,'save',*flags,'-o',pending,*[IMAGES[k] for k in kinds]])
            checksum=digest(pending)
            pending.replace(target)
        images={}
        for kind in kinds:
            images[kind]={'id':identities[kind],'tag':IMAGES[kind],'file':file,'sha256':checksum}
        write_json(directory/'images.json',images)
    else:
        manifest=json.loads((directory/'images.json').read_text());loaded=set();hashes={}
        for kind,item in manifest.items():
            name=item['file']
            if kind not in IMAGES or item['tag']!=IMAGES[kind]:raise WorkflowError('Archive contains an unexpected image tag')
            if Path(name).name!=name:raise WorkflowError('Invalid image archive name')
            if name not in hashes:hashes[name]=digest(directory/name)
            if hashes[name]!=item['sha256']:raise WorkflowError('Invalid image archive or hash')
            if name not in loaded:call([rt.engine,'load','-i',directory/name]);loaded.add(name)
            call([rt.engine,'tag',item['id'],item['tag']])
            if rt.image_id(kind).removeprefix('sha256:')!=item['id'].removeprefix('sha256:'):raise WorkflowError('Imported image identity mismatch')
