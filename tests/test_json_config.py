"""The public case format needs only the Python standard library."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from pcb_thermal.common import WorkflowError, read_config


class JsonConfig(unittest.TestCase):
    def test_json_case_without_site_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'case.json'
            expected = {'schema':1, 'name':'PCB °C', 'execution':{'backend':'cpu'}}
            path.write_text(json.dumps(expected), encoding='utf-8')
            self.assertEqual(read_config(path), expected)
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
            result = subprocess.run([sys.executable, '-S', '-c',
                'import json,sys; from pcb_thermal.common import read_config; print(json.dumps(read_config(sys.argv[1])))',
                str(path)], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout), expected)

    def test_non_json_syntax_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'case.json'
            for text in ['schema: 1\nname: board\n', '{"name":"board",}', '{"schema":']:
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaisesRegex(WorkflowError, 'Invalid JSON'):
                        read_config(path)

    def test_case_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'case.json'
            for value in [[], 'board', 1, None]:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaisesRegex(WorkflowError, 'mapping'):
                        read_config(path)

    def test_missing_case_has_a_workflow_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(WorkflowError, 'Cannot read'):
                read_config(Path(directory)/'missing.json')
