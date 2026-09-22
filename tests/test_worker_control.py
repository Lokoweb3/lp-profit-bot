import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from lp_profit_bot import seller, worker_control as w


class WorkerControlTests(unittest.TestCase):
    def test_unknown_worker_rejected_without_signaling(self):
        with patch.object(w.signal,'pidfd_send_signal') as send:
            with self.assertRaises(seller.SellerError):w.stop('arbitrary-pid')
            send.assert_not_called()

    def test_unrelated_process_does_not_match(self):
        self.assertFalse(w.matches(os.getpid(),'lp_profit_bot.auto_convert'))

    def test_stopped_worker_ignores_old_running_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)):
            state=Path(tmp)/'state';state.mkdir()
            (state/'auto-convert-runtime.json').write_text(json.dumps({'mode':'live','status':'CHECKING','updated_at':time.time()}))
            status=w.status()['conversion']
            self.assertFalse(status['running'])
            self.assertIsNone(status['activity'])
            self.assertIsNone(status['mode'])

    def test_stop_all_continues_after_one_failure(self):
        with patch.object(w,'stop',side_effect=[seller.SellerError('blocked')]+['Stopped']*(len(w.WORKERS)-1)) as stop:
            with self.assertRaises(seller.SellerError):w.stop_all()
            self.assertEqual([c.args[0] for c in stop.call_args_list],list(w.WORKERS))

    def test_real_stop_targets_only_selected_harmless_worker(self):
        # Isolated fake package: these workers only hold locks and sleep; no trading code runs.
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)):
            root=Path(tmp);package=root/'lp_profit_bot';package.mkdir();(package/'__init__.py').write_text('')
            (root/'state').mkdir()
            processes=[]
            try:
                for key in ('spy','conversion'):
                    _,module,lock,runtime=w.WORKERS[key]
                    (package/(module.split('.')[-1]+'.py')).write_text(
                        "import fcntl,time,json,os\nfrom pathlib import Path\n"
                        f"f=open('state/{lock}','a')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
                        f"Path('state/{runtime}').write_text(json.dumps({{'pid':os.getpid(),'mode':'simulation','status':'CHECKING','updated_at':time.time()}}))\n"
                        "time.sleep(30)\n")
                    processes.append(subprocess.Popen([sys.executable,'-m',module],cwd=root,
                                     env=dict(os.environ,PYTHONPATH=''),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
                deadline=time.monotonic()+5
                while not all(w.running(key) for key in ('spy','conversion')) and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertTrue(w.running('spy'));self.assertTrue(w.running('conversion'))
                self.assertIn('stopped',w.stop('spy'))
                processes[0].wait(timeout=2)
                self.assertIsNone(processes[1].poll())
                self.assertTrue(w.running('conversion'))
                self.assertIn('already stopped',w.stop('spy'))
                self.assertIn('All trading scripts stopped',w.stop_all())
                processes[1].wait(timeout=2)
                self.assertFalse(w.running('conversion'))
            finally:
                for process in processes:
                    if process.poll() is None:process.terminate()
                    process.wait(timeout=3)
