import base64
import json
import os
import stat
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from solders.pubkey import Pubkey
from solders.signature import Signature

from lp_profit_bot import (auto_bridge, auto_convert, buy_googl_bridge as flow,
                           credentials, execution_barrier, seller, worker_control,
                           xnt_conversion)


class AuditFixTests(unittest.TestCase):
    def test_f01_completion_during_status_preview_cannot_become_purchase(self):
        # The HTTP-level action binding has dedicated coverage in test_dashboard;
        # this verifies the engine's completed state is inert without repeat=True.
        asset=flow.ASSETS['spy']
        row=flow.new_attempt(asset,11_000_000)
        row.update(stage='completed',swap_signature='swap',bridge_signature='bridge',
                   destination_signature='receipt')
        with patch.object(flow,'read_journal',return_value=row), patch.object(flow,'prepare_swap') as prepare:
            result=flow.cycle(False,'spy',spend_raw=25_000_000,repeat=False)
        self.assertEqual(result['status'],'COMPLETED')
        prepare.assert_not_called()

    def test_f04_stop_barrier_waits_for_submission_and_rejects_stale_generation(self):
        with tempfile.TemporaryDirectory() as root, patch.object(seller,'ROOT',Path(root)):
            generation=execution_barrier.snapshot();entered=threading.Event();release=threading.Event()
            def submitting():
                with execution_barrier.submission(generation):
                    entered.set();release.wait(2)
            first=threading.Thread(target=submitting);first.start();self.assertTrue(entered.wait(1))
            stopped=threading.Event()
            second=threading.Thread(target=lambda:(execution_barrier.stop(),stopped.set()))
            second.start();time.sleep(.05);self.assertFalse(stopped.is_set())
            release.set();first.join(1);second.join(1);self.assertTrue(stopped.is_set())
            with self.assertRaises(seller.SellerError):
                with execution_barrier.submission(generation): pass
        self.assertIn('buy_stock_bridge',worker_control.WORKERS)
        self.assertIn('buy_googl_bridge',worker_control.WORKERS)

    def _message(self, *, amount=11_000_000, out=3_000_000, minimum=2_985_000,
                 destination=None, signers=1, compute_price=10_000):
        asset=flow.ASSETS['spy'];source=flow.associated(flow.USDC,flow.TOKEN_CLASSIC)
        destination=destination or flow.associated(asset['sol_mint'],flow.TOKEN_2022)
        keys=[seller.WALLET,flow.COMPUTE,flow.JUPITER,flow.TOKEN_CLASSIC,source,destination,
              flow.SYSTEM,asset['sol_mint'],'11111111111111111111111111111112']
        ix=lambda p,a,d:SimpleNamespace(program_id_index=p,accounts=a,data=d)
        route=flow.ROUTE+b'plan'+struct.pack('<QQHB',amount,out,50,0)
        instructions=[ix(1,[],b'\x02'+struct.pack('<I',1_000_000)),
                      ix(1,[],b'\x03'+struct.pack('<Q',compute_price)),
                      ix(2,[3,0,4,5,8,7],route)]
        return SimpleNamespace(account_keys=[Pubkey.from_string(k) for k in keys],instructions=instructions,
            address_table_lookups=(),header=SimpleNamespace(num_required_signatures=signers),
            is_maybe_writable=lambda index:index in (4,5)),asset,minimum

    def test_f02_jupiter_route_is_bound_to_preview_and_fee(self):
        message,asset,minimum=self._message()
        quote={'inAmount':'11000000','outAmount':'3000000','otherAmountThreshold':str(minimum),
               'slippageBps':50}
        self.assertTrue(flow.validate_jupiter_transaction(message,quote,asset,minimum))
        for changed in ({'inAmount':'12000000'}, {'outAmount':'3100000'}):
            with self.assertRaises(seller.SellerError):
                flow.validate_jupiter_transaction(message,dict(quote,**changed),asset,minimum)
        bad,asset,minimum=self._message(destination=flow.associated(flow.GOOGL,flow.TOKEN_2022))
        with self.assertRaises(seller.SellerError):flow.validate_jupiter_transaction(bad,quote,asset,minimum)
        bad,asset,minimum=self._message(signers=2)
        with self.assertRaises(seller.SellerError):flow.validate_jupiter_transaction(bad,quote,asset,minimum)
        bad,asset,minimum=self._message(compute_price=200_000)
        with self.assertRaises(seller.SellerError):flow.validate_jupiter_transaction(bad,quote,asset,minimum)

    def test_f02_lookup_tables_are_resolved_and_owner_checked(self):
        address=Pubkey.new_unique();lookup=SimpleNamespace(account_key=Pubkey.new_unique(),
            writable_indexes=bytes([0]),readonly_indexes=bytes())
        message=SimpleNamespace(account_keys=[Pubkey.new_unique()],address_table_lookups=[lookup])
        raw=b'\0'*56+bytes(address)
        value={'value':{'owner':flow.LOOKUP_TABLE_PROGRAM,'data':[base64.b64encode(raw).decode(),'base64']}}
        with patch.object(flow.bridge,'solana_rpc',return_value=value):
            self.assertEqual(flow.resolved_message_keys(message)[1],str(address))
        value['value']['owner']=flow.SYSTEM
        with patch.object(flow.bridge,'solana_rpc',return_value=value):
            with self.assertRaises(seller.SellerError):flow.resolved_message_keys(message)

    def test_f03_bridge_transaction_lock_has_no_undefined_reference(self):
        with tempfile.TemporaryDirectory() as root, patch.object(seller,'ROOT',Path(root)), \
             patch.object(auto_bridge,'TX_LOCK',Path(root)/'state'/'bridge.lock'):
            with auto_bridge.transaction_lock(): pass

    def test_f07_conversion_journal_lock_preserves_concurrent_append(self):
        signature=str(Signature.default());second_signature=str(Signature.from_bytes(bytes([1])*64))
        with tempfile.TemporaryDirectory() as root, patch.object(seller,'ROOT',Path(root)), \
             patch.object(xnt_conversion,'STATE',Path(root)/'state'/'journal.json'), \
             patch.object(xnt_conversion,'JOURNAL_LOCK',Path(root)/'state'/'journal.lock'):
            seller.atomic_write(xnt_conversion.STATE,{'wallet':seller.WALLET,'entries':[]})
            entered=threading.Event();release=threading.Event()
            def first():
                with xnt_conversion.journal_lock():
                    journal=xnt_conversion._read_journal();entered.set();release.wait(2)
                    journal['entries'].append({'signature':signature,'amount_raw':1,'status':'pending'})
                    seller.atomic_write(xnt_conversion.STATE,journal)
            def second():
                with xnt_conversion.journal_lock():
                    journal=xnt_conversion._read_journal()
                    journal['entries'].append({'signature':second_signature,'amount_raw':2,'status':'pending'})
                    seller.atomic_write(xnt_conversion.STATE,journal)
            a=threading.Thread(target=first);b=threading.Thread(target=second)
            a.start();self.assertTrue(entered.wait(1));b.start();time.sleep(.05);release.set();a.join();b.join()
            self.assertEqual(len(xnt_conversion.read_journal()['entries']),2)

    def test_f05_receipt_uses_expected_account_not_secondary_balance(self):
        mint=flow.ASSETS['spy']['sol_mint'];expected=flow.associated(mint,flow.TOKEN_2022)
        def row(index,amount):return {'accountIndex':index,'owner':seller.WALLET,'mint':mint,
            'uiTokenAmount':{'amount':str(amount)}}
        tx={'transaction':{'signatures':['sig'],'message':{'accountKeys':[seller.WALLET,expected,str(Pubkey.new_unique())]}},
            'meta':{'err':None,'preTokenBalances':[row(1,10),row(2,500)],
                    'postTokenBalances':[row(1,13),row(2,900)]}}
        with patch.object(flow.bridge,'solana_rpc',return_value=tx):
            self.assertEqual(flow.transaction_receipt('sig',mint),3)

    def test_f06_credential_and_cache_reads_reject_symlinks_and_modes(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);secret=root/'key';secret.write_text('token\n');secret.chmod(0o644)
            with patch.dict(os.environ,{'X1_API_KEY':''}),patch.object(credentials,'KEY_FILE',secret), \
                 self.assertRaises(Exception):credentials.load_key()
            secret.chmod(0o600)
            with patch.dict(os.environ,{'X1_API_KEY':''}),patch.object(credentials,'KEY_FILE',secret):
                self.assertEqual(credentials.load_key(),'token')
            target=root/'target';target.write_text(json.dumps({'wallet':seller.WALLET,'receipts':{}}))
            state=root/'state';state.mkdir(mode=0o700);link=state/'cache.json';link.symlink_to(target)
            with patch.object(auto_convert,'CACHE',link),self.assertRaises(OSError):auto_convert.load_cache()


if __name__=='__main__':unittest.main()
