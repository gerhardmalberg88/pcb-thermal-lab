"""File and subprocess helpers; no shell evaluation of case inputs."""
import hashlib
import json
import os
import subprocess
import fcntl
from functools import wraps
from pathlib import Path

ROOT = Path(os.environ.get('PCB_THERMAL_ROOT',Path(__file__).resolve().parents[2])).resolve()
CACHE = ROOT / ".cache"


class WorkflowError(Exception):
    pass


def serial_workflow(function):
    """One memory-intensive pipeline per checkout, also across CLI processes."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        CACHE.mkdir(parents=True, exist_ok=True)
        with (CACHE/'workflow.lock').open('a') as lock:
            try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Waiting for the other thermal workflow to release memory...',flush=True)
                fcntl.flock(lock, fcntl.LOCK_EX)
            return function(*args, **kwargs)
    return wrapped


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise WorkflowError("Case configuration must be a mapping.")
        return data
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Invalid JSON in {path}: {error}") from error
    except (OSError, ValueError) as error:
        raise WorkflowError(f"Cannot read {path}: {error}") from error


def call(args, *, log=None, capture=False, check=True, cwd=None, env=None):
    args = [str(arg) for arg in args]
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with Path(log).open("a") as stream:
            stream.write("\nCOMMAND " + json.dumps(args) + "\n")
            stream.flush()
            process = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                for line in process.stdout:
                    print(line, end="", flush=True)
                    stream.write(line)
                    stream.flush()
                code = process.wait()
            except BaseException:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                raise
        if check and code:
            raise WorkflowError(f"Command exited {code}; see {log}")
        return subprocess.CompletedProcess(args,code)
    try:
        result = subprocess.run(args, cwd=cwd, env=env, text=True,
                                capture_output=capture, check=False)
    except OSError as error:
        raise WorkflowError(f"Cannot execute {args[0]}: {error}") from error
    if check and result.returncode:
        raise WorkflowError(f"{args[0]} exited {result.returncode}: {result.stderr or result.stdout or ''}")
    return result


def positive(value):
    original = value
    value = int(value)
    if isinstance(original, bool) or (isinstance(original, float) and original != value) or value < 1:
        raise ValueError("must be at least 1")
    return value
