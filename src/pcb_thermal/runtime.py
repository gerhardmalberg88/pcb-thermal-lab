"""Rootless container execution and explicit CPU/CUDA selection."""
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from .common import ROOT, CACHE, WorkflowError, call

IMAGES = {kind: f"localhost/pcb-thermal-{kind}:0.1" for kind in ("tools", "cpu", "cuda")}


class Runtime:
    def __init__(self, engine=None):
        self.engine = engine or os.environ.get("PCB_THERMAL_ENGINE", "podman")
        if self.engine not in ("podman", "docker", "native"):
            raise WorkflowError("PCB_THERMAL_ENGINE must be podman, docker or native")

    def native_env(self):
        env=dict(os.environ)
        prefix=CACHE/'native/elmer'
        env['PATH']=str(CACHE/'native/paraview/bin')+':'+str(prefix/'bin')+':'+env.get('PATH','')
        env['ELMER_HOME']=str(prefix)
        env['LD_LIBRARY_PATH']=str(CACHE/'qt-root/usr/lib/x86_64-linux-gnu')+':'+str(prefix/'lib/elmersolver')+':'+env.get('LD_LIBRARY_PATH','')
        env['PYTHONPATH']=str(ROOT/'src')
        return env

    def image_exists(self, kind):
        if self.engine=='native':
            return kind!='cuda' and (kind=='tools' or (CACHE/'native/elmer/bin/ElmerSolver').is_file())
        result = call([self.engine, "image", "inspect", IMAGES[kind]], capture=True, check=False)
        return result.returncode == 0

    def image_id(self, kind):
        if self.engine=='native':
            from .common import digest,fingerprint
            files=[CACHE/'native/elmer/bin/ElmerSolver',Path('/usr/bin/gmsh'),Path('/usr/bin/kicad-cli'),Path('/usr/bin/pvpython')]
            return 'native:'+fingerprint({str(p):digest(p) for p in files if p.is_file()})
        result = call([self.engine, "image", "inspect", IMAGES[kind]], capture=True)
        return json.loads(result.stdout)[0]["Id"]

    def gpu_check(self, count=1):
        if not self.image_exists("cuda"):
            return False, "CUDA image is not built"
        args = self.base("cuda", gpu_count=count)
        result = call(args + [IMAGES["cuda"], "/usr/local/bin/pcb-thermal-cuda-check"],
                      capture=True, check=False)
        return result.returncode == 0, (result.stdout if result.returncode == 0 else result.stderr).strip()

    def select(self, requested, count=1):
        if requested == "cpu":
            # Deliberately do not call gpu_check, nvidia-smi or inspect CUDA here.
            if not self.image_exists("cpu"):
                raise WorkflowError("CPU image missing; run pcb-thermal build --profile cpu")
            return "cpu", "CPU explicitly selected"
        if requested not in ("auto", "cuda"):
            raise WorkflowError(f"Unknown execution backend: {requested}")
        available, reason = self.gpu_check(count)
        if available:
            return "cuda", "CUDA device preflight passed"
        if requested == "cuda":
            raise WorkflowError(f"CUDA requested but unavailable: {reason}")
        if not self.image_exists("cpu"):
            raise WorkflowError(f"CUDA unavailable ({reason}); CPU image is also missing")
        return "cpu", f"Using CPU: {reason}"

    def base(self, kind, gpu_count=0):
        # Xvfb's readiness handshake cannot target a shell running as PID 1.
        # An init process also reaps children left by GUI and MPI launchers.
        args = [self.engine, "run", "--rm", "--init", "--network=none", "--ipc=private"]
        owner = os.environ.get('PCB_THERMAL_BATCH_ID')
        if owner:
            args += ['--label', f'pcb-thermal.batch={owner}']
        if self.engine == "podman":
            # Image USER metadata can otherwise override keep-id's default and
            # leave generated files owned by a subordinate host UID.
            args += ["--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}"]
        else:
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        args += ["--env", "HOME=/tmp/pcb-thermal-home", "--entrypoint", "",
                 "--env", "MPLCONFIGDIR=/tmp/pcb-thermal-matplotlib",
                 "--env", "PYTHONPATH=/workflow/src", "--volume", f"{ROOT}:/workflow:ro"]
        if gpu_count:
            if self.engine == "podman":
                for index in range(gpu_count):
                    args += ["--device", f"nvidia.com/gpu={index}"]
            else:
                args += ["--gpus", str(gpu_count)]
        return args

    def stop_batch(self, owner):
        """Remove only containers carrying this invocation's unique ownership label."""
        if self.engine == 'native': return
        result = subprocess.run([self.engine, 'ps', '-aq', '--filter',
                                 f'label=pcb-thermal.batch={owner}'],
                                capture_output=True, text=True, timeout=15, check=True)
        containers = result.stdout.split()
        if containers:
            removal = [self.engine, 'rm', '-f'] + (['-t', '5'] if self.engine == 'podman' else [])
            subprocess.run(removal + containers,
                           capture_output=True, text=True, timeout=30, check=True)

    def stop_container(self, name):
        # --rm may already have removed it after the client was interrupted.
        removal = [self.engine, 'rm', '-f'] + (['-t', '5'] if self.engine == 'podman' else [])
        subprocess.run(removal + [name],
                       capture_output=True, text=True, timeout=20, check=False)

    def run(self, kind, command, *, project=None, output=None, gpu_count=0,
            env=None, log=None, capture=False, check=True, gui=False,memory_gib=None):
        if self.engine=='native':
            if gpu_count:raise WorkflowError('Native diagnostic runtime has no CUDA solver; use the CUDA image')
            if output:Path(output).mkdir(parents=True,exist_ok=True)
            mappings={'/workflow':str(ROOT),'/work':str(Path(output).resolve()) if output else '/tmp',
                      '/project':str(Path(project).resolve()) if project else '/tmp'}
            args=[]
            for part in command:
                value=str(part)
                for source,target in mappings.items():
                    if value==source or value.startswith(source+'/'):value=target+value[len(source):];break
                args.append(value)
            environment=self.native_env();environment.update(env or {})
            return call(args,cwd=output,env=environment,log=log,capture=capture,check=check)
        args = self.base(kind, gpu_count)
        owned_name = None
        if os.environ.get('PCB_THERMAL_BATCH_ID') and not gui:
            owned_name = 'pcb-thermal-' + uuid.uuid4().hex
            args += ['--name', owned_name]
        if memory_gib:
            budget=str(int(float(memory_gib)*1024**3))
            args += ['--memory',budget,'--memory-swap',budget]
        if project:
            args += ["--volume", f"{Path(project).resolve()}:/project:ro"]
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            args += ["--volume", f"{Path(output).resolve()}:/work:rw", "--workdir", "/work"]
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        temporary_auth=None
        if gui:
            gui_home=CACHE/'gui'/Path(command[0]).name/'home'
            gui_home.mkdir(parents=True,exist_ok=True)
            display = os.environ.get("DISPLAY")
            auth = os.environ.get("XAUTHORITY", str(Path.home() / ".Xauthority"))
            if not display or not Path(auth).is_file():
                raise WorkflowError("GUI requires DISPLAY and a readable XAUTHORITY cookie file")
            # A container hostname differs from the host's FamilyLocal Xauth
            # entry. Forward only this display's existing cookie as FamilyWild;
            # do not disable X authentication or expose every user's cookies.
            listed=subprocess.run(['xauth','-f',auth,'nlist',display],capture_output=True,text=True,check=True)
            entries=[line for line in listed.stdout.splitlines() if line.strip()]
            if not entries:raise WorkflowError('No Xauthority cookie matches DISPLAY')
            fd,temporary_auth=tempfile.mkstemp(prefix='xauthority-',dir=gui_home.parent);os.close(fd)
            try:
                subprocess.run(['xauth','-f',temporary_auth,'nmerge','-'],input='\n'.join('ffff'+line[4:] for line in entries)+'\n',text=True,capture_output=True,check=True)
            except BaseException:
                Path(temporary_auth).unlink(missing_ok=True);raise
            args += ["--env", f"DISPLAY={display}", "--env", "XAUTHORITY=/tmp/xauthority",
                     "--env","LIBGL_ALWAYS_SOFTWARE=1","--env","QT_X11_NO_MITSHM=1",
                     "--env","QT_XCB_NO_MITSHM=1",
                     "--env","HOME=/gui-home","--volume",f"{gui_home}:/gui-home:rw",
                     "--volume", "/tmp/.X11-unix:/tmp/.X11-unix:ro",
                     "--volume", f"{temporary_auth}:/tmp/xauthority:ro"]
        try:return call(args + [IMAGES[kind]] + list(command), log=log, capture=capture, check=check)
        except BaseException:
            if owned_name: self.stop_container(owned_name)
            raise
        finally:
            if temporary_auth:Path(temporary_auth).unlink(missing_ok=True)
