"""Offline lifecycle tests; cold-download acceptance runs separately on each Spark."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).with_name('sync.py')


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = self.root / 'catalog.yaml'
        self.catalog.write_text('fixture')
        spec = importlib.util.spec_from_file_location('model_sync_test', SOURCE)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'HF_HOME': str(self.root), 'MODEL_CATALOG_PATH': str(self.catalog)}):
            spec.loader.exec_module(self.module)
        self.entries = [{'repo': 'example/a', 'revision': 'a'*40}, {'repo': 'example/b', 'revision': 'b'*40}]
        self.download = Mock(side_effect=['/cache/a', '/cache/b'])
        self.hub = types.SimpleNamespace(snapshot_download=self.download,
                    constants=types.SimpleNamespace(HF_HUB_DISABLE_XET=True, HF_HUB_ENABLE_HF_TRANSFER=False))
        self.yaml = types.SimpleNamespace(safe_load=lambda f: {'models': self.entries})

    def cycle(self):
        with patch.dict(sys.modules, {'yaml': self.yaml, 'huggingface_hub': self.hub}), patch.dict(os.environ, {'MODEL_DOWNLOAD_WORKERS': '1'}):
            return self.module.sync_once()

    def test_success_pins_revisions_one_worker_and_preserves_files(self):
        keep = self.root / 'existing-model'
        keep.write_text('preserve')
        self.assertTrue(self.cycle())
        self.download.assert_any_call('example/a', revision='a'*40, max_workers=1)
        self.download.assert_any_call('example/b', revision='b'*40, max_workers=1)
        status = json.loads((self.root / 'catalog-status.json').read_text())
        self.assertEqual([e['state'] for e in status['models']], ['ready', 'ready'])
        self.assertEqual(keep.read_text(), 'preserve')
        self.assertFalse((self.root / 'catalog-status.json.tmp').exists())

    def test_download_failure_keeps_going_and_publishes_error(self):
        self.download.side_effect = [RuntimeError('download failed'), '/cache/b']
        self.assertFalse(self.cycle())
        status = json.loads((self.root / 'catalog-status.json').read_text())
        self.assertEqual([e['state'] for e in status['models']], ['error', 'ready'])
        self.assertEqual(self.download.call_count, 2)

    def test_failed_replace_preserves_previous_status(self):
        target = self.root / 'catalog-status.json'
        target.write_text('{"previous":true}')
        with patch.object(self.module.os, 'replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.cycle()
        self.assertEqual(json.loads(target.read_text()), {'previous': True})

    def test_supervisor_delays_follow_exit_status(self):
        for result, expected in [(0, 21600), (1, 300), (-9, 300)]:
            with self.subTest(result=result):
                handlers = {}
                child = Mock()
                child.wait.return_value = result
                def stop_wait(_):
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                with patch.object(self.module.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), patch.object(self.module.subprocess, 'Popen', return_value=child) as popen, patch.object(self.module.time, 'sleep', side_effect=stop_wait), patch('builtins.print') as output:
                    self.module.supervise()
                self.assertEqual(popen.call_args.args[0][-1], '--once')
                output.assert_called_with(f'downloader exited: code={result}; next sync in {expected}s', flush=True)

    def run_real_supervisor(self, slow, ignore_term=False):
        # Fake only remote download I/O; exercise real parent/child and OS signals.
        (self.root / 'yaml.py').write_text('def safe_load(f): return {"models":[{"repo":"test","revision":"abc"}]}\n')
        (self.root / 'huggingface_hub.py').write_text(
            'import os,time,signal\nfrom pathlib import Path\n'
            'class constants:\n HF_HUB_DISABLE_XET=True\n HF_HUB_ENABLE_HF_TRANSFER=False\n'
            'def snapshot_download(*a,**k):\n'
            f' signal.signal(signal.SIGTERM, signal.SIG_IGN) if {ignore_term} else None\n'
            ' Path(os.environ["HF_HOME"],"child.pid").write_text(str(os.getpid()))\n'
            f' time.sleep({60 if slow else 0})\n return "/cache/test"\n')
        env = dict(os.environ, HF_HOME=str(self.root), MODEL_CATALOG_PATH=str(self.catalog), PYTHONPATH=str(self.root))
        process = subprocess.Popen([sys.executable, str(SOURCE)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        assert process.stderr is not None
        try:
            target = self.root / ('child.pid' if slow else 'catalog-status.json')
            deadline = time.monotonic() + 5
            while not target.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(process.stderr.read().decode())
                time.sleep(.02)
            self.assertTrue(target.exists())
            time.sleep(.05)
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            bound = 24 if ignore_term else 3
            self.assertEqual(process.wait(timeout=bound), 0)
            self.assertLess(time.monotonic() - started, bound)
            if ignore_term:
                self.assertGreaterEqual(time.monotonic() - started, 20)
            pid = int((self.root / 'child.pid').read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stderr.close()
            marker = self.root / 'child.pid'
            if marker.exists():
                try:
                    os.kill(int(marker.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_sigterm_escalates_for_uncooperative_child(self):
        self.run_real_supervisor(slow=True, ignore_term=True)

    def test_signal_handler_takes_no_lock(self):
        # Inject TERM inside a locked wait; a flag-only handler must return.
        import threading
        lock = threading.Lock()
        child = Mock()
        child.poll.return_value = None
        handlers = {}
        def locked_wait(timeout=None):
            if timeout == 1:
                with lock:
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                raise subprocess.TimeoutExpired('test', 1)
            return 0
        child.wait.side_effect = locked_wait
        with patch.object(self.module.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), patch.object(self.module.subprocess, 'Popen', return_value=child):
            self.module.supervise()
        child.terminate.assert_called_once()
        child.wait.assert_any_call(timeout=20)

    def test_sigterm_while_downloading_reaps_child(self):
        self.run_real_supervisor(slow=True)

    def test_sigterm_while_idle_exits_promptly(self):
        self.run_real_supervisor(slow=False)


if __name__ == '__main__':
    unittest.main()
