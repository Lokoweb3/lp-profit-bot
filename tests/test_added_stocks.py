import importlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from lp_profit_bot import dashboard as d,stock_policy as p,stock_references as refs,worker_control as w
from lp_profit_bot.ninja import NinjaError
from tests.test_dashboard import DashboardHTTPTests

KEYS=('meta','coin','pltr','amd','nvda')

class AddedStockTests(unittest.TestCase):
    def test_registry_routes_mints_and_shared_lock(self):
        from lp_profit_bot.spy_seller import native_lock
        for key in KEYS:
            module=importlib.import_module('lp_profit_bot.'+key+'_seller')
            monitor=importlib.import_module('lp_profit_bot.'+key+'_monitor')
            self.assertEqual(module.ASSET.mint,monitor.MINT)
            self.assertEqual(module.ASSET.pool,monitor.POOL)
            self.assertIs(module.native_lock,native_lock)
            self.assertEqual(w.WORKERS[key][1],module.__name__)
            with patch.object(module,'stock_snapshot',return_value={}) as snapshot:
                module.snapshot();snapshot.assert_called_once_with(monitor.MINT,monitor.POOL)

    def test_cached_batch_keeps_original_timestamp_and_reuses_request(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(refs,'CACHE',Path(temp)/'cache.json'), patch.object(refs.comparison,'fetch_reference_batch') as fetch:
            stamp=time.time()-400
            fetch.return_value={p.STOCKS[k].reference:{'usd':'100','last_updated_at':stamp} for k in KEYS}
            for k in KEYS:
                value=refs.fetch_reference(p.STOCKS[k].reference)
                self.assertEqual(value[p.STOCKS[k].reference]['last_updated_at'],stamp)
            fetch.assert_called_once_with(refs.IDS)

    def test_failed_reference_batch_cools_down_without_returning_old_price(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(refs,'CACHE',Path(temp)/'cache.json'), patch.object(refs.comparison,'fetch_reference_batch',side_effect=NinjaError('unavailable')) as fetch:
            for k in KEYS:
                with self.assertRaises(NinjaError):refs.fetch_reference(p.STOCKS[k].reference)
            self.assertEqual(fetch.call_count,1)

    def test_new_asset_invalidates_prior_batch_cache(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(refs,'CACHE',Path(temp)/'cache.json'), patch.object(refs.comparison,'fetch_reference_batch') as fetch:
            refs.CACHE.write_text(json.dumps({'fetched_at':time.time(),'ids':['amd-xstock'],'data':{}}))
            fetch.return_value={'nvidia-xstock':{'usd':'200','last_updated_at':time.time()}}
            self.assertEqual(refs.fetch_reference('nvidia-xstock')['nvidia-xstock']['usd'],'200')
            fetch.assert_called_once_with(refs.IDS)

    def test_each_start_launches_only_fixed_asset_command(self):
        for key in KEYS:
            module=importlib.import_module('lp_profit_bot.'+key+'_seller')
            with tempfile.TemporaryDirectory() as temp, patch.object(d.seller,'ROOT',Path(temp)), patch.object(d,'seller_running',side_effect=[False,True]), patch.object(module,'read_journal',return_value={'halted':False}), patch.object(d.subprocess,'Popen') as launch:
                launch.return_value.poll.return_value=None
                getattr(d,'start_'+key+'_seller')()
                self.assertEqual(launch.call_args.args[0][2:],[module.__name__,'--live','--watch'])

class AddedStockHTTPTests(DashboardHTTPTests):
    def test_added_routes_require_token_and_dispatch_exact_asset(self):
        token=self.token
        headers={'Origin':f'http://127.0.0.1:{self.port}','X-Dashboard-Token':token}
        for key in KEYS:
            with patch.object(d,'start_'+key+'_seller',return_value='Started') as start:
                route=f'/api/{key}/seller/start'
                self.assertEqual(self.request(route,'POST')[0],403)
                start.assert_not_called()
                self.assertEqual(self.request(route,'POST',headers)[0],200)
                start.assert_called_once_with()
            with patch.object(w,'stop',return_value='Stopped') as stop:
                route=f'/api/scripts/{key}/stop'
                self.assertEqual(self.request(route,'POST')[0],403)
                self.assertEqual(self.request(route,'POST',headers)[0],200)
                stop.assert_called_once_with(key)
