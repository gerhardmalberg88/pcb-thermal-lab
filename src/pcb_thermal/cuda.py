"""AMGX image build; CUDA is optional and never a CPU dependency."""
import json
import os
import re
import shutil
from .common import ROOT,CACHE,WorkflowError,call,write_json
from .runtime import IMAGES

def build_cuda(rt,pins,context,jobs,arch,version):
    from .build import fetch
    if not re.fullmatch(r'\d+',arch):raise WorkflowError('CUDA architecture must be an integer, such as 75')
    if version!='12.9.1':raise WorkflowError('This pinned recipe supports CUDA 12.9.1; add and validate another toolkit pin before selecting it')
    source=fetch('amgx.tar.gz',pins['assets']['amgx.tar.gz']);target=context/'amgx.tar.gz'
    if target.exists():target.unlink()
    os.link(source,target);shutil.copy2(ROOT/'scripts/cuda-check.cu',context/'cuda-check.cu')
    shutil.copy2(ROOT/'scripts/patch-elmer-cuda.py',context/'patch-elmer-cuda.py')
    cuda_image=pins['cuda_image']
    call([rt.engine,'build','--layers','--build-arg','CUDA_IMAGE='+cuda_image,'--build-arg','CPU_IMAGE='+IMAGES['cpu'],
          '--build-arg',f'BUILD_JOBS={jobs}','--build-arg','CUDA_ARCH='+arch,'-t',IMAGES['cuda'],
          '-f',ROOT/'containers/Containerfile.cuda',context],log=CACHE/'logs/build-cuda.log')
    dest=ROOT/'env/locks'/('cuda-'+arch+'-'+version);dest.mkdir(parents=True,exist_ok=True)
    write_json(dest/'image.json',{'id':rt.image_id('cuda'),'pins':pins,'architecture':arch})
