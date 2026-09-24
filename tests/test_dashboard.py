import http.client
import json
import tempfile
from pathlib import Path
import threading
import time
import unittest
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock

from lp_profit_bot import dashboard as d
from lp_profit_bot import seller


class DashboardTests(unittest.TestCase):
    def test_public_status_totals_and_no_private_fields(self):
        cache = d.DashboardData()
        now = time.time()
        cache.chain = {"pool_price": "400", "fetched_at": now}
        cache.reference = {"price": "350", "updated_at": now}
        journal = {"halted": False, "entries": [
            {"signature": "one", "amount_raw": 500000, "minimum_output_raw": 2000000, "status": "finalized", "private_key": "NEVER_RETURN"},
            {"signature": "two", "amount_raw": 500000, "status": "pending"}]}
        with patch.object(seller, "read_journal", return_value=journal), \
             patch.object(d, "seller_running", return_value=True), \
             patch.object(d, "read_public_file", return_value=(None, None)):
            status = cache.status()
        self.assertEqual(status["journal"]["confirmed"], "0.005")
        self.assertEqual(status["journal"]["reserved"], "0.01")
        self.assertIsNone(status["journal"]["remaining"])
        self.assertIsNone(status["policy"]["cap"])
        self.assertTrue(status["market_fresh"])
        self.assertNotIn("NEVER_RETURN", json.dumps(status))

    def test_bridge_history_exposes_only_public_receipt_fields(self):
        from lp_profit_bot import auto_bridge
        cache = d.DashboardData()
        bridge = {'entries':[{'signature':'x1tx','destination_signature':'soltx',
                 'amount_raw':100_000_000,'status':'completed','created_at':1.0,
                 'private_key':'NEVER_RETURN'}]}
        with patch.object(auto_bridge,'read_journal',return_value=bridge), \
             patch.object(d,'seller_running',return_value=True):
            status=cache.status()
        self.assertEqual(status['auto_bridge']['entries'][0]['destination_signature'],'soltx')
        self.assertNotIn('NEVER_RETURN',json.dumps(status))

    def test_stock_purchase_status_exposes_stage_times_without_private_fields(self):
        from lp_profit_bot import buy_googl_bridge as flow
        row={'stage':'completed','spend_raw':11_000_000,'swap_signature':'swap',
             'bridge_signature':'bridge','destination_signature':'receipt','created_at':100,
             'swap_finalized_at':110,'bridge_submitted_at':120,'bridge_finalized_at':130,
             'completed_at':140,'private_key':'NEVER_RETURN'}
        with patch.object(flow,'read_journal',return_value=row), \
             patch.object(flow,'read_history',return_value=[row]), \
             patch.object(d,'seller_running',return_value=False):
            status=d.DashboardData().status()
        purchase=status['stock_purchase']['spy']
        self.assertEqual(purchase['bridge_finalized_at'],130)
        self.assertEqual(purchase['history'][0]['completed_at'],140)
        self.assertNotIn('NEVER_RETURN',json.dumps(status))

    def test_stale_reference_suppresses_gap(self):
        cache = d.DashboardData()
        cache.chain = {"pool_price": "400", "fetched_at": time.time()}
        cache.reference = {"price": "350", "updated_at": time.time()-301}
        with patch.object(seller, "read_journal", return_value={"halted": False, "entries": []}), \
             patch.object(d, "seller_running", return_value=False), \
             patch.object(d, "read_public_file", return_value=(None, None)):
            self.assertIsNone(cache.status()["gap_percent"])

    def test_failed_refresh_keeps_old_data_marked_stale(self):
        cache = d.DashboardData()
        cache.chain = {"pool_price": "400", "fetched_at": time.time()}
        with patch.object(seller, "snapshot", side_effect=ValueError("secret response")), \
             patch.object(seller, "reference_price", side_effect=ValueError("secret response")):
            cache.refresh()
        self.assertEqual(cache.chain["pool_price"], "400")
        self.assertEqual(len(cache.errors), 2)
        self.assertNotIn("secret response", str(cache.errors))

    def test_telemetry_failure_cannot_interrupt_seller(self):
        with patch.object(seller, "atomic_write", side_effect=OSError("disk full")):
            seller.runtime_status(True, "CHECKING")


class DashboardHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache = d.DashboardData()
        cache.status = lambda: {"read_only": True}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), d.handler_for(cache, 0))
        cls.port = cls.server.server_port
        cls.server.RequestHandlerClass = d.handler_for(cache, cls.port)
        cls.token = cls.server.RequestHandlerClass.control_token
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        result = response.status, body, dict(response.getheaders())
        connection.close()
        return result

    def test_page_assets_and_status(self):
        for path in ("/", "/app.js", "/styles.css", "/api/status"):
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("control_token", json.loads(self.request("/api/status")[1]))
        self.assertTrue(json.loads(self.request("/api/status")[1])["controls_unlocked"])
        status, page, headers = self.request('/')
        self.assertIn(b'id="stock-purchase"', page)
        self.assertIn(b'id="wxnt-route-title"', page)
        self.assertIn(b'J8Uev16V9jFxLRBSqvy78AcE5sxBh8Ax6gyGhwGMZYTE', page)
        self.assertNotIn(b'id="unlock-controls"', page)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def test_browser_session_requires_cookie_and_local_origin(self):
        cookie = self.request('/api/status')[2]['Set-Cookie'].split(';', 1)[0]
        headers = {'Origin': f'http://127.0.0.1:{self.port}', 'Cookie': cookie}
        self.assertEqual(self.request('/api/control/unlock', 'POST', headers)[0], 404)
        self.assertEqual(self.request('/api/control/unlock', 'POST',
                                      dict(headers, Cookie='dashboard_session=wrong'))[0], 403)
        self.assertEqual(self.request('/api/control/unlock', 'POST', {'Cookie': cookie})[0], 403)

    def test_auto_conversion_start_route(self):
        cookie=self.request('/api/status')[2]['Set-Cookie'].split(';', 1)[0]
        valid={'Origin':f'http://127.0.0.1:{self.port}','Cookie':cookie}
        with patch.object(d,'start_auto_conversion',return_value='Started') as start:
            self.assertEqual(self.request('/api/conversion/start','POST')[0],403)
            self.assertEqual(self.request('/api/conversion/start')[0],404)
            start.assert_not_called()
            self.assertEqual(self.request('/api/conversion/start','POST',valid)[0],200)
            start.assert_called_once_with()

    def test_stock_purchase_preview_requires_token_and_confirmation_is_single_use(self):
        from lp_profit_bot import buy_googl_bridge as flow
        valid = {'Origin': f'http://127.0.0.1:{self.port}',
                 'X-Dashboard-Token': self.token, 'Content-Type': 'application/json'}
        body = json.dumps({'stock': 'spy', 'amount': '11'})
        preview = {'status': 'SWAP_READY', 'asset': 'SPY', 'spend_usdc': '11',
                   'quoted_stock': '0.014', 'minimum_stock': '0.0135',
                   'bridge_minimum_stock': '0.013'}
        with patch.object(flow, 'cycle', side_effect=[preview, {'status': 'SWAP_PENDING', 'signature': 'mock-signature'}]) as cycle, \
             patch.object(flow, 'read_journal', return_value={'stage': 'new'}), \
             patch.object(flow, 'process_lock', return_value=nullcontext()), \
             patch.object(d, 'start_stock_purchase_watcher', return_value=True) as watcher:
            self.assertEqual(self.request('/api/stock-purchase/preview', 'POST', body=body)[0], 403)
            self.assertEqual(self.request('/api/stock-purchase/preview', 'POST', valid,
                                          json.dumps({'stock': 'unknown'}))[0], 409)
            cycle.assert_not_called()
            status, payload, _ = self.request('/api/stock-purchase/preview', 'POST', valid, body)
            self.assertEqual(status, 200)
            quote = json.loads(payload)
            self.assertTrue(quote['quote_id'])
            self.assertEqual(quote['stock'], 'spy')
            watcher.assert_not_called()
            confirm = json.dumps({'quote_id': quote['quote_id']})
            status, payload, _ = self.request('/api/stock-purchase/confirm', 'POST', valid, confirm)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(payload)['tracking_started'])
            self.assertEqual(self.request('/api/stock-purchase/confirm', 'POST', valid, confirm)[0], 409)
            self.assertEqual(cycle.call_args_list[0].args, (False, 'spy'))
            self.assertEqual(cycle.call_args_list[0].kwargs, {'spend_raw':11_000_000,'repeat':False})
            self.assertEqual(cycle.call_args_list[1].args, (True, 'spy', 1_350_000))
            self.assertEqual(cycle.call_args_list[1].kwargs['spend_raw'],11_000_000)
            self.assertFalse(cycle.call_args_list[1].kwargs['repeat'])
            self.assertIsInstance(cycle.call_args_list[1].kwargs['barrier_generation'],int)
            watcher.assert_called_once()
            self.assertEqual(watcher.call_args.args[0],'spy')

    def test_stock_purchase_rechecks_journal_before_confirmation(self):
        from lp_profit_bot import buy_googl_bridge as flow
        valid = {'Origin': f'http://127.0.0.1:{self.port}',
                 'X-Dashboard-Token': self.token, 'Content-Type': 'application/json'}
        preview = {'status': 'SWAP_READY', 'asset': 'SPY', 'spend_usdc': '11',
                   'quoted_stock': '0.014', 'minimum_stock': '0.0135',
                   'bridge_minimum_stock': '0.013'}
        with patch.object(flow, 'cycle', return_value=preview) as cycle, \
             patch.object(flow, 'read_journal', side_effect=[{'stage': 'new'}, {'stage': 'new'}, {'stage': 'swap_pending'}]), \
             patch.object(flow, 'process_lock', return_value=nullcontext()), \
             patch.object(d, 'start_stock_purchase_watcher') as watcher:
            status, payload, _ = self.request('/api/stock-purchase/preview', 'POST', valid, json.dumps({'stock':'spy','amount':'11'}))
            self.assertEqual(status, 200)
            quote_id = json.loads(payload)['quote_id']
            self.assertEqual(self.request('/api/stock-purchase/confirm', 'POST', valid,
                                          json.dumps({'quote_id':quote_id}))[0], 409)
            cycle.assert_called_once_with(False, 'spy', spend_raw=11_000_000, repeat=False)
            watcher.assert_not_called()

    def test_completed_during_preview_is_status_check_not_repeat_purchase(self):
        from lp_profit_bot import buy_googl_bridge as flow
        valid={'Origin':f'http://127.0.0.1:{self.port}','X-Dashboard-Token':self.token,
               'Content-Type':'application/json'}
        completed={'stage':'completed','swap_signature':'swap','bridge_signature':'bridge',
                   'destination_signature':'receipt'}
        with patch.object(flow,'read_journal',side_effect=[{'stage':'swap_pending'},completed,completed]), \
             patch.object(flow,'read_history',return_value=[completed]), \
             patch.object(flow,'cycle',side_effect=[{'status':'COMPLETED'}, {'status':'COMPLETED'}]) as cycle, \
             patch.object(flow,'process_lock',return_value=nullcontext()), \
             patch.object(d,'start_stock_purchase_watcher') as watcher:
            status,payload,_=self.request('/api/stock-purchase/preview','POST',valid,
                json.dumps({'stock':'spy','amount':'11'}))
            self.assertEqual(status,200)
            preview=json.loads(payload);self.assertEqual(preview['action'],'check_status')
            status,payload,_=self.request('/api/stock-purchase/confirm','POST',valid,
                json.dumps({'quote_id':preview['quote_id']}))
            self.assertEqual(status,200)
            self.assertEqual(json.loads(payload)['status'],'COMPLETED')
            self.assertEqual(cycle.call_args_list[0].kwargs['repeat'],False)
            self.assertEqual(cycle.call_args_list[1].kwargs['repeat'],False)
            self.assertFalse(cycle.call_args_list[1].args[0])
            watcher.assert_not_called()

    def test_bridge_preview_and_confirm_require_token_and_single_use(self):
        from lp_profit_bot import auto_bridge
        token=self.token
        valid={'Origin':f'http://127.0.0.1:{self.port}','X-Dashboard-Token':token,
               'Content-Type':'application/json'}
        body=json.dumps({'amount':'20'})
        with patch.object(auto_bridge,'preview',return_value={'amount_raw':20_000_000,
             'fee_usdc':'1','expires_at':time.time()+30}) as preview, \
             patch.object(auto_bridge,'execute_manual',return_value={'signature':'x1tx'}) as execute:
            self.assertEqual(self.request('/api/bridge/preview','POST',body=body)[0],403)
            status,data,_=self.request('/api/bridge/preview','POST',valid,body)
            self.assertEqual(status,200)
            quote_id=json.loads(data)['quote_id']
            self.assertEqual(preview.call_count,1)
            confirm=json.dumps({'quote_id':quote_id})
            self.assertEqual(self.request('/api/bridge/confirm','POST',valid,confirm)[0],200)
            self.assertEqual(self.request('/api/bridge/confirm','POST',valid,confirm)[0],409)
            self.assertEqual(execute.call_count,1)

    def test_stop_routes_require_token_and_never_accept_arbitrary_targets(self):
        token=self.token
        valid={'Origin':f'http://127.0.0.1:{self.port}','X-Dashboard-Token':token}
        with patch.object(d.worker_control,'stop',return_value='Stopped') as stop, \
             patch.object(d.worker_control,'stop_all',return_value='All stopped') as stop_all:
            for key in ('googl','spy','conversion'):
                path='/api/scripts/'+key+'/stop'
                self.assertEqual(self.request(path,'POST')[0],403)
                self.assertEqual(self.request(path)[0],404)
            stop.assert_not_called()
            self.assertEqual(self.request('/api/scripts/unknown/stop','POST',valid)[0],404)
            for key in ('googl','spy','conversion'):
                self.assertEqual(self.request('/api/scripts/'+key+'/stop','POST',valid)[0],200)
                stop.assert_called_with(key)
            self.assertEqual(self.request('/api/scripts/stop-all','POST')[0],403)
            stop_all.assert_not_called()
            self.assertEqual(self.request('/api/scripts/stop-all','POST',valid)[0],200)
            stop_all.assert_called_once_with()

    def test_spy_start_uses_protected_dedicated_route(self):
        token = self.token
        headers = {'Origin': f'http://127.0.0.1:{self.port}', 'X-Dashboard-Token': token}
        with patch.object(d, 'start_spy_seller', return_value='Started') as spy_start, \
             patch.object(d, 'start_seller') as googl_start:
            self.assertEqual(self.request('/api/spy/seller/start', 'POST')[0],403)
            self.assertEqual(self.request('/api/spy/seller/start')[0],404)
            spy_start.assert_not_called()
            self.assertEqual(self.request('/api/spy/seller/start', 'POST',headers)[0],200)
            spy_start.assert_called_once_with()
            googl_start.assert_not_called()

    def test_conversion_routes_require_token_and_quote_is_single_use(self):
        from lp_profit_bot import xnt_conversion
        token = self.token
        valid = {'Origin': f'http://127.0.0.1:{self.port}', 'X-Dashboard-Token': token,
                 'Content-Type': 'application/json'}
        def post(path, body, headers):
            connection = http.client.HTTPConnection('127.0.0.1', self.port)
            connection.request('POST', path, json.dumps(body), headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read()) if response.status != 403 else response.read()
            connection.close()
            return result
        with patch.object(xnt_conversion, 'preview', return_value={'expires_at': time.time()+30}) as preview, \
             patch.object(xnt_conversion, 'execute', return_value={'message': 'submitted'}) as execute:
            self.assertEqual(post('/api/xnt/quote', {'amount':'1'}, {})[0],403)
            preview.assert_not_called()
            status, quote = post('/api/xnt/quote', {'amount':'1'},valid)
            self.assertEqual(status,200)
            self.assertEqual(post('/api/xnt/confirm', {'quote_id':quote['quote_id']},valid)[0],200)
            self.assertEqual(post('/api/xnt/confirm', {'quote_id':quote['quote_id']},valid)[0],409)
            execute.assert_called_once()

    def test_secrets_traversal_and_mutations_blocked(self):
        for path in ("/.secrets/bot-wallet.json", "/../.secrets/ninja-api-key", "/%2e%2e/.secrets/bot-wallet.json", "/api/sell", "/state/seller-journal.json"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/status", "POST")[0], 403)

    def test_untrusted_host_rejected(self):
        self.assertEqual(self.request("/api/status", headers={"Host": "evil.example"})[0], 403)

    def test_start_requires_origin_token_and_exact_route(self):
        token = self.token
        valid = {"Origin": f"http://127.0.0.1:{self.port}", "X-Dashboard-Token": token}
        with patch.object(d, "start_seller", return_value="Started") as start:
            for headers in ({}, {"Origin": valid["Origin"]},
                            dict(valid, Origin="https://evil.example"),
                            dict(valid, **{"X-Dashboard-Token": "wrong"}),
                            dict(valid, Host="evil.example")):
                self.assertEqual(self.request("/api/seller/start", "POST", headers)[0], 403)
            self.assertEqual(self.request("/api/seller/start")[0], 404)
            self.assertEqual(self.request("/api/unknown", "POST", valid)[0], 404)
            start.assert_not_called()
            self.assertEqual(self.request("/api/seller/start", "POST", valid)[0], 200)
            start.assert_called_once_with()


class SellerStartTests(unittest.TestCase):
    def test_stock_bridge_watcher_uses_fixed_selected_command(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, patch.object(seller, 'ROOT', Path(tmp)), \
             patch.object(d.subprocess, 'Popen', return_value=process) as spawn:
            self.assertTrue(d.start_stock_purchase_watcher('spy',7))
            self.assertEqual(spawn.call_args.args[0],
                             [d.sys.executable, '-m', 'lp_profit_bot.buy_stock_bridge',
                              '--stock', 'spy', '--live', '--watch', '--barrier-generation', '7'])
            with self.assertRaises(seller.SellerError):
                d.start_stock_purchase_watcher('unknown',7)

    def test_existing_seller_never_spawns(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(seller, "ROOT", Path(tmp)), \
             patch.object(d, "seller_running", return_value=True), patch.object(d.subprocess, "Popen") as spawn:
            self.assertIn("already running", d.start_seller())
            spawn.assert_not_called()

    def test_halted_journal_never_spawns(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(seller, "ROOT", Path(tmp)), \
             patch.object(d, "seller_running", return_value=False), \
             patch.object(seller, "read_journal", return_value={"halted": True, "entries": []}), \
             patch.object(d.subprocess, "Popen") as spawn:
            with self.assertRaises(seller.SellerError):
                d.start_seller()
            spawn.assert_not_called()

    def test_former_cap_does_not_block_dashboard_start(self):
        process = Mock()
        process.poll.return_value = None
        journal = {"halted": False, "entries": [{"amount_raw": seller.CHUNK_RAW}] * 14}
        with tempfile.TemporaryDirectory() as tmp, patch.object(seller, "ROOT", Path(tmp)), \
             patch.object(d, "seller_running", side_effect=[False, True]), \
             patch.object(seller, "read_journal", return_value=journal), \
             patch.object(d.subprocess, "Popen", return_value=process) as spawn:
            self.assertIn("Live seller started", d.start_seller())
            spawn.assert_called_once()

    def test_fixed_live_command_and_log(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, patch.object(seller, "ROOT", Path(tmp)), \
             patch.object(d, "seller_running", side_effect=[False, True]), \
             patch.object(seller, "read_journal", return_value={"halted": False, "entries": []}), \
             patch.object(d.subprocess, "Popen", return_value=process) as spawn:
            self.assertIn("Live seller started", d.start_seller())
            self.assertEqual(spawn.call_args.args[0],
                             [d.sys.executable, "-m", "lp_profit_bot.seller", "--live", "--watch"])
            self.assertNotIn("shell", spawn.call_args.kwargs)
            self.assertTrue((Path(tmp)/"state"/"seller-dashboard.log").exists())


    def test_spy_already_running_and_halt_block_launch(self):
        from lp_profit_bot import spy_seller
        for running, journal in ((True, None), (False, {'halted':True,'entries':[]})):
            with tempfile.TemporaryDirectory() as tmp, patch.object(seller,'ROOT',Path(tmp)), \
                 patch.object(d,'seller_running',return_value=running), \
                 patch.object(spy_seller,'read_journal',return_value=journal),patch.object(d.subprocess,'Popen') as spawn:
                if running:
                    self.assertIn('already running',d.start_spy_seller())
                else:
                    with self.assertRaises(seller.SellerError):d.start_spy_seller()
                spawn.assert_not_called()

    def test_spy_start_uses_fixed_live_command(self):
        from lp_profit_bot import spy_seller
        process=Mock();process.poll.return_value=None
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)), \
             patch.object(d,'seller_running',side_effect=[False,True]) as running, \
             patch.object(spy_seller,'read_journal',return_value={'halted':False,'entries':[]}), \
             patch.object(d.subprocess,'Popen',return_value=process) as spawn:
            self.assertIn('SPY.X → XNT',d.start_spy_seller())
            self.assertEqual(spawn.call_args.args[0],[d.sys.executable,'-m','lp_profit_bot.spy_seller','--live','--watch'])
            self.assertEqual(running.call_args.args,('spy-seller.lock',))


    def test_auto_converter_start_guards_and_fixed_command(self):
        from lp_profit_bot import xnt_conversion
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)), \
             patch.object(d,'seller_running',return_value=True),patch.object(d.subprocess,'Popen') as spawn:
            self.assertIn('already running',d.start_auto_conversion());spawn.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)), \
             patch.object(d,'seller_running',return_value=False),patch.object(d.subprocess,'Popen') as spawn, \
             patch.object(xnt_conversion,'read_journal',return_value={'entries':[{'status':'failed','source':'spy_proceeds_auto'}]}):
            with self.assertRaises(seller.SellerError):d.start_auto_conversion()
            spawn.assert_not_called()
        process=Mock();process.poll.return_value=None
        with tempfile.TemporaryDirectory() as tmp,patch.object(seller,'ROOT',Path(tmp)), \
             patch.object(d,'seller_running',side_effect=[False,True]),patch.object(d.subprocess,'Popen',return_value=process) as spawn, \
             patch.object(xnt_conversion,'read_journal',return_value={'entries':[]}):
            self.assertIn('Automatic conversion started',d.start_auto_conversion())
            self.assertEqual(spawn.call_args.args[0],[d.sys.executable,'-m','lp_profit_bot.auto_convert','--live','--watch'])
