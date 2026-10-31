import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcb_thermal.build import transfer
from pcb_thermal.common import WorkflowError, digest
from pcb_thermal.runtime import IMAGES


class ImageTransfer(unittest.TestCase):
    def existing(self, root):
        archive=Path(root)/'pcb-thermal-images.tar';archive.write_bytes(b'previous valid archive')
        manifest=Path(root)/'images.json'
        manifest.write_text(json.dumps({kind:{'id':'old-'+kind,'tag':IMAGES[kind],
            'file':archive.name,'sha256':digest(archive)} for kind in ('cpu','tools')}))
        return archive,manifest

    def operation(self, fail=False):
        def call(args, **kwargs):
            if 'inspect' in args:return subprocess.CompletedProcess(args,0,stdout='[{"Size": 100}]')
            if 'save' in args:
                Path(args[args.index('-o')+1]).write_bytes(b'new archive')
                if fail:raise WorkflowError('simulated interrupted export')
                return subprocess.CompletedProcess(args,0)
            raise AssertionError(args)
        return call

    def test_failed_replacement_preserves_previous_archive_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            archive,manifest=self.existing(d);before=[p.read_bytes() for p in (archive,manifest)]
            with patch('pcb_thermal.build.Runtime') as runtime,patch('pcb_thermal.build.call',side_effect=self.operation(fail=True)):
                runtime.return_value.engine='podman';runtime.return_value.image_id.side_effect=lambda kind:'new-'+kind
                with self.assertRaises(WorkflowError):transfer(d,'cpu')
            self.assertEqual(before,[p.read_bytes() for p in (archive,manifest)])
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()),['images.json','pcb-thermal-images.tar'])

    def test_successful_replacement_updates_manifest_and_one_archive(self):
        with tempfile.TemporaryDirectory() as d:
            archive,manifest=self.existing(d)
            with patch('pcb_thermal.build.Runtime') as runtime,patch('pcb_thermal.build.call',side_effect=self.operation()):
                runtime.return_value.engine='podman';runtime.return_value.image_id.side_effect=lambda kind:'new-'+kind
                transfer(d,'cpu')
            result=json.loads(manifest.read_text())
            self.assertEqual(archive.read_bytes(),b'new archive')
            self.assertEqual(result['cpu']['id'],'new-cpu')
            self.assertTrue(all(v['sha256']==digest(archive) for v in result.values()))
            self.assertEqual(len(list(Path(d).iterdir())),2)

    def test_does_not_replace_an_unowned_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/'pcb-thermal-images.tar';archive.write_bytes(b'unrelated')
            with patch('pcb_thermal.build.Runtime') as runtime:
                runtime.return_value.engine='podman';runtime.return_value.image_id.side_effect=lambda kind:'new-'+kind
                with self.assertRaises(WorkflowError):transfer(d,'cpu')
            self.assertEqual(archive.read_bytes(),b'unrelated')
