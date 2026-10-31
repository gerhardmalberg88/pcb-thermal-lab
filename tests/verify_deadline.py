"""Integration check: timeout stops its container and preserves unrelated work/logs."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from pcb_thermal.common import ROOT, write_json
from pcb_thermal.runtime import Runtime, IMAGES
from pcb_thermal.study_runner import BudgetExceeded, time_limit

rt = Runtime()
if rt.engine == 'native':
    raise SystemExit('This check requires Podman or Docker')
owner = uuid.uuid4().hex
control = 'pcb-thermal-deadline-control-' + uuid.uuid4().hex
out = ROOT/'results/validation/deadline'
out.mkdir(parents=True, exist_ok=True)
previous = os.environ.pop('PCB_THERMAL_BATCH_ID', None)
try:
    subprocess.run(rt.base('cpu') + ['--name', control, '-d', IMAGES['cpu'],
                                    'sleep', '90'], check=True, capture_output=True)
    os.environ['PCB_THERMAL_BATCH_ID'] = owner
    started = time.monotonic()
    expired = False
    try:
        with time_limit(3):
            rt.run('cpu', ['sh', '-c', 'echo deadline-check-started; sleep 60'], log=out/'stage.log')
    except BudgetExceeded:
        expired = True
    rt.stop_batch(owner)
    owned = subprocess.run([rt.engine, 'ps', '-aq', '--filter',
                            'label=pcb-thermal.batch='+owner], check=True, capture_output=True, text=True)
    control_state = subprocess.run([rt.engine, 'inspect', '--format', '{{.State.Running}}', control],
                                   check=True, capture_output=True, text=True)
    evidence = dict(expired=expired, cleanup_seconds=time.monotonic()-started,
                    owned_containers_remaining=owned.stdout.split(),
                    independent_control_running=control_state.stdout.strip()=='true',
                    interrupted_log_preserved='deadline-check-started' in (out/'stage.log').read_text())
    evidence['pass'] = expired and not owned.stdout.strip() and evidence['independent_control_running'] and evidence['interrupted_log_preserved']
    write_json(out/'checks.json', evidence)
    print(json.dumps(evidence, indent=2))
    if not evidence['pass']: raise SystemExit(1)
finally:
    rt.stop_batch(owner)
    rt.stop_container(control)
    if previous is None: os.environ.pop('PCB_THERMAL_BATCH_ID', None)
    else: os.environ['PCB_THERMAL_BATCH_ID'] = previous
