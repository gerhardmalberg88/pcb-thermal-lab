import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

class ResourceGuard(unittest.TestCase):
    def test_refuses_command_when_host_reserve_is_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            result=Path(d)/'resources.json';marker=Path(d)/'should-not-exist'
            p=subprocess.run([sys.executable,'-m','pcb_thermal.measure',str(result),'--min-available-gib','1000000','--',sys.executable,'-c',f'from pathlib import Path; Path({str(marker)!r}).touch()'],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,125)
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads(result.read_text())['stop_reason'],'insufficient_host_memory_before_start')

    def test_workflow_lock_serializes_separate_processes(self):
        with tempfile.TemporaryDirectory() as d:
            code='''from pcb_thermal.common import serial_workflow
from pathlib import Path
import sys,time
@serial_workflow
def job():
 p=Path(sys.argv[1]);p.write_text(str(time.monotonic()));time.sleep(.3)
 p.with_suffix('.done').write_text(str(time.monotonic()))
job()
'''
            env=dict(os.environ,PCB_THERMAL_ROOT=d)
            first=subprocess.Popen([sys.executable,'-c',code,str(Path(d)/'first')],env=env,stdout=subprocess.DEVNULL)
            import time
            deadline=time.monotonic()+5
            while not (Path(d)/'first').exists() and time.monotonic()<deadline:time.sleep(.01)
            second=subprocess.Popen([sys.executable,'-c',code,str(Path(d)/'second')],env=env,stdout=subprocess.DEVNULL)
            self.assertEqual(first.wait(timeout=5),0);self.assertEqual(second.wait(timeout=5),0)
            self.assertGreaterEqual(float((Path(d)/'second').read_text()),float((Path(d)/'first.done').read_text()))

    def test_stops_only_owned_solver_when_budget_exceeded(self):
        with tempfile.TemporaryDirectory() as d:
            result=Path(d)/'resources.json'
            process=subprocess.run([sys.executable,'-m','pcb_thermal.measure',str(result),'--max-rss-gib','0.05','--',sys.executable,'-c','import time; payload=bytearray(100*1024*1024); time.sleep(20)'],capture_output=True,text=True,timeout=15)
            record=json.loads(result.read_text())
            self.assertNotEqual(process.returncode,0)
            self.assertTrue(record['memory_limit_exceeded'])
            self.assertGreater(record['peak_process_tree_rss_bytes_sampled'],record['rss_limit_bytes'])
