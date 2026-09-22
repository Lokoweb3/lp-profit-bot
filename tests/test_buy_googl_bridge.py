import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lp_profit_bot import buy_googl_bridge as flow


class BuyGooglBridgeTests(unittest.TestCase):
    def test_wrapped_sol_cleanup_requires_matching_setup_and_wallet_destination(self):
        wsol_ata = flow.associated(flow.WSOL, flow.TOKEN_CLASSIC)
        keys = [flow.s.WALLET, flow.s.ATA, flow.TOKEN_CLASSIC, flow.JUPITER,
                flow.bridge.SYSTEM, wsol_ata, flow.associated(flow.USDC,flow.TOKEN_CLASSIC)]
        def ix(program, accounts, data):
            return SimpleNamespace(program_id_index=program, accounts=accounts, data=data)
        setup=ix(1,[0,5,0,6,4,2],b'\x01')
        route=ix(3,[],b'route')
        close=ix(2,[5,0,0],b'\x09')
        message=SimpleNamespace(account_keys=keys,instructions=[setup,route,close])
        self.assertTrue(flow.validate_swap_programs(message))
        message.instructions=[setup,route,ix(2,[6,0,0],b'\x09')]
        with self.assertRaises(flow.s.SellerError):
            flow.validate_swap_programs(message)
        message.instructions=[route,close]
        with self.assertRaises(flow.s.SellerError):
            flow.validate_swap_programs(message)
        message.instructions=[setup,route,ix(2,[5,0,0],b'\x04')]
        with self.assertRaises(flow.s.SellerError):
            flow.validate_swap_programs(message)

    def test_quote_rejects_below_bridge_minimum(self):
        response={'inputMint':flow.USDC,'outputMint':flow.GOOGL,'inAmount':'10000000',
                  'swapMode':'ExactIn','slippageBps':50,'otherAmountThreshold':'2800000',
                  'priceImpactPct':'0.001'}
        with patch.object(flow,'request_json',return_value=response):
            with self.assertRaises(flow.s.SellerError):
                flow.quote(10_000_000)

    def test_amount_accepts_precise_spend_without_business_cap(self):
        self.assertEqual(flow.parse_usdc_amount('125.123456'), 125_123_456)
        self.assertEqual(flow.parse_usdc_amount('11.000001'), 11_000_001)
        for amount in ('0', '-1', '1.1234567', '1e3'):
            with self.assertRaises(flow.s.SellerError):
                flow.parse_usdc_amount(amount)
        with self.assertRaises(flow.s.SellerError):
            flow.quote(2**64)

    def test_solana_token_accounts_use_correct_programs(self):
        with patch.object(flow.s, 'WALLET', '11111111111111111111111111111111'):
            self.assertNotEqual(flow.associated(flow.USDC,flow.TOKEN_CLASSIC),
                                flow.associated(flow.USDC,flow.TOKEN_2022))
            self.assertEqual(flow.associated(flow.GOOGL,flow.TOKEN_2022),
                             'ECH14mf3spKKT14qWnmiLagbqBzGUzo9X9ZGG22H63F2')

    def test_supported_stocks_match_live_bridge_route_fields(self):
        config = {'solana': {'config': {'programId': flow.bridge.PROGRAM, 'paused': False}, 'tokens': []},
                  'x1': {'config': {'programId': flow.bridge.PROGRAM, 'paused': False}, 'tokens': []}}
        for asset in flow.ASSETS.values():
            common = {'symbol': asset['symbol'], 'decimals': 8, 'paused': False}
            config['solana']['tokens'].append(dict(common, mint=asset['sol_mint'], isNative=True,
                minAmount='3000000', percentageFeeBps=25, flatFeeAmount='0'))
            config['x1']['tokens'].append(dict(common, mint=asset['x1_mint'], isNative=False))
        with patch.object(flow.bridge, 'api', return_value=config):
            for asset in flow.ASSETS.values():
                self.assertEqual(flow.bridge_token(asset)[1]['mint'], asset['sol_mint'])
            config['x1']['tokens'][1]['mint'] = flow.ASSETS['googl']['x1_mint']
            with self.assertRaises(flow.s.SellerError):
                flow.bridge_token(flow.ASSETS['spy'])

    def test_aapl_route_uses_authorized_mints_and_program_escrow(self):
        asset=flow.ASSETS['aapl']
        self.assertEqual(asset['sol_mint'],'XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp')
        self.assertEqual(asset['x1_mint'],'u7i4awutsHa9qcy6YdDQKfjER16i9fx4PRhG4ZqUXZ5')
        escrow=str(flow.Pubkey.find_program_address(
            [b'vault',bytes(flow.Pubkey.from_string(asset['sol_mint']))],
            flow.Pubkey.from_string(flow.bridge.PROGRAM))[0])
        self.assertEqual(asset['escrow'],escrow)
        changed=dict(asset,escrow='11111111111111111111111111111111')
        with patch.object(flow.bridge,'solana_rpc',return_value=1):
            with self.assertRaisesRegex(flow.s.SellerError,'escrow changed'):
                flow.build_bridge(3_000_000,{'config':{}},{},changed)

    def test_selected_stock_quote_must_clear_its_bridge_minimum(self):
        asset = flow.ASSETS['tsla']
        response = {'inputMint': flow.USDC, 'outputMint': asset['sol_mint'],
                    'inAmount': str(flow.DEFAULT_USDC_RAW), 'swapMode': 'ExactIn',
                    'slippageBps': flow.MAX_SLIPPAGE_BPS,
                    'outAmount': '2510000', 'otherAmountThreshold': '2499999',
                    'priceImpactPct': '0.001'}
        with patch.object(flow, 'request_json', return_value=response) as request:
            with self.assertRaises(flow.s.SellerError):
                flow.quote(asset=asset, minimum_raw=2_500_000)
            self.assertIn(asset['sol_mint'], request.call_args.args[0])
            response['otherAmountThreshold'] = '2500000'
            self.assertEqual(flow.quote(asset=asset, minimum_raw=2_500_000), response)

    def test_stock_journals_are_separate_and_bound_to_mints(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            spy = flow.ASSETS['spy']
            path = flow.journal_path(spy)
            self.assertNotEqual(path, flow.journal_path(flow.ASSETS['tsla']))
            row = flow.read_journal(spy)
            row.update(stage='swap_pending', swap_signature=str(flow.Signature.default()))
            flow.s.atomic_write(path, row)
            self.assertEqual(flow.read_journal(spy)['asset'], 'spy')
            row['sol_mint'] = flow.ASSETS['tsla']['sol_mint']
            flow.s.atomic_write(path, row)
            with self.assertRaises(flow.s.SellerError):
                flow.read_journal(spy)

    def test_completed_purchase_can_begin_new_attempt_without_losing_history(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            asset = flow.ASSETS['googl']
            old = flow.new_attempt(asset, 11_000_000)
            old.update(stage='completed',swap_signature=str(flow.Signature.default()),
                       bridge_signature=str(flow.Signature.default()),destination_signature='receipt')
            flow.s.atomic_write(flow.journal_path(asset), old)
            token = {'minAmount':'1000000','maxAmount':'100000000','dailyCapRemaining':'100000000'}
            q = {'outAmount':'2500000','otherAmountThreshold':'2400000'}
            with patch.object(flow,'bridge_token',return_value=({},token)), \
                 patch.object(flow,'quote',return_value=q) as quote, \
                 patch.object(flow,'prepare_swap') as prepare, \
                 patch.object(flow,'signer') as signer:
                result=flow.cycle(False,'googl',spend_raw=25_000_000,repeat=True)
            self.assertEqual(result['spend_usdc'],'25')
            self.assertEqual(len(flow.read_history(asset)),1)
            self.assertEqual(flow.read_journal(asset)['stage'],'completed')
            quote.assert_called_once_with(amount_raw=25_000_000,asset=asset,minimum_raw=1_000_000)
            prepare.assert_not_called()
            signer.assert_not_called()
            flow.write_attempt(asset,flow.new_attempt(asset,25_000_000),append=True)
            rows=flow.read_history(asset)
            self.assertEqual([r['stage'] for r in rows],['completed','new'])
            self.assertEqual(rows[0]['destination_signature'],'receipt')
            self.assertEqual(rows[1]['spend_raw'],25_000_000)

    def test_repeat_confirmation_failure_preserves_old_receipt_without_new_attempt(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            asset = flow.ASSETS['googl']
            old = flow.new_attempt(asset, 11_000_000)
            old.update(stage='completed',swap_signature=str(flow.Signature.default()),
                       bridge_signature=str(flow.Signature.default()),destination_signature='old-receipt')
            flow.s.atomic_write(flow.journal_path(asset), old)
            token = {'minAmount':'1000000','maxAmount':'100000000','dailyCapRemaining':'100000000'}
            q = {'outAmount':'2500000','otherAmountThreshold':'2400000'}
            with patch.object(flow,'bridge_token',return_value=({},token)), \
                 patch.object(flow,'quote',return_value=q), \
                 patch.object(flow,'prepare_swap',side_effect=flow.s.SellerError('test stop')), \
                 patch.object(flow,'signer') as signer:
                with self.assertRaises(flow.s.SellerError):
                    flow.cycle(True,'googl',2_400_000,spend_raw=25_000_000,repeat=True)
            rows=flow.read_history(asset)
            self.assertEqual([r['stage'] for r in rows],['completed'])
            self.assertEqual(rows[0]['destination_signature'],'old-receipt')
            signer.assert_not_called()

    def test_worse_repeat_quote_does_not_create_purchase_record(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            asset=flow.ASSETS['googl']
            old=flow.new_attempt(asset,11_000_000)
            old.update(stage='completed',swap_signature=str(flow.Signature.default()),
                       bridge_signature=str(flow.Signature.default()),destination_signature='old-receipt')
            flow.s.atomic_write(flow.journal_path(asset),old)
            token={'minAmount':'1000000','maxAmount':'100000000','dailyCapRemaining':'100000000'}
            q={'outAmount':'2500000','otherAmountThreshold':'2399999'}
            with patch.object(flow,'bridge_token',return_value=({},token)), \
                 patch.object(flow,'quote',return_value=q), \
                 patch.object(flow,'prepare_swap') as prepare, \
                 patch.object(flow,'signer') as signer:
                with self.assertRaises(flow.s.SellerError):
                    flow.cycle(True,'googl',2_400_000,spend_raw=15_000_000,repeat=True)
            self.assertEqual(len(flow.read_history(asset)),1)
            self.assertEqual(flow.read_journal(asset)['stage'],'completed')
            prepare.assert_not_called()
            signer.assert_not_called()

    def test_preview_for_other_stock_never_prepares_or_signs(self):
        asset = flow.ASSETS['amd']
        row = {'stage': 'new', 'spend_raw':flow.DEFAULT_USDC_RAW}
        token = {'minAmount': '2000000', 'maxAmount': '100000000',
                 'dailyCapRemaining': '100000000'}
        q = {'outAmount': '2400000', 'otherAmountThreshold': '2200000'}
        with patch.object(flow, 'read_journal', return_value=row), \
             patch.object(flow, 'bridge_token', return_value=({}, token)), \
             patch.object(flow, 'quote', return_value=q), \
             patch.object(flow, 'prepare_swap') as prepare, \
             patch.object(flow, 'signer') as signer:
            result = flow.cycle(False, 'amd')
        self.assertEqual(result['status'], 'SWAP_READY')
        self.assertEqual(result['solana_mint'], asset['sol_mint'])
        prepare.assert_not_called()
        signer.assert_not_called()

    def test_confirm_rejects_a_worse_quote_before_preparing_transaction(self):
        token = {'minAmount': '1300000', 'maxAmount': '100000000',
                 'dailyCapRemaining': '100000000'}
        quote = {'outAmount': '1400000', 'otherAmountThreshold': '1350000'}
        with patch.object(flow, 'read_journal', return_value={'stage': 'new', 'spend_raw':flow.DEFAULT_USDC_RAW}), \
             patch.object(flow, 'bridge_token', return_value=({}, token)), \
             patch.object(flow, 'quote', return_value=quote), \
             patch.object(flow, 'prepare_swap') as prepare, \
             patch.object(flow, 'signer') as signer:
            with self.assertRaises(flow.s.SellerError):
                flow.cycle(True, 'spy', 1_360_000)
        prepare.assert_not_called()
        signer.assert_not_called()

    def test_watcher_continues_pending_journal_until_completed(self):
        with patch.object(flow, 'process_lock', return_value=nullcontext()), \
             patch.object(flow, 'cycle', side_effect=[{'status':'SWAP_PENDING'},
                                                      {'status':'COMPLETED'}]) as cycle, \
             patch.object(flow.time, 'sleep') as sleep, \
             patch.object(flow.argparse.ArgumentParser, 'parse_args', return_value=type('Args', (),
                 {'stock':'spy', 'live':True, 'watch':True, 'amount':'11', 'new_purchase':False})()):
            flow.main()
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_finalized_purchase_records_observation_time_without_signing(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            asset=flow.ASSETS['spy']
            row=flow.new_attempt(asset,11_000_000)
            row.update(stage='swap_pending',swap_signature=str(flow.Signature.default()),created_at=100)
            flow.write_attempt(asset,row)
            token={'minAmount':'2000000','maxAmount':'4000000','dailyCapRemaining':'4000000'}
            with patch.object(flow.bridge,'solana_rpc',return_value={'value':[{'confirmationStatus':'finalized','err':None}]}), \
                 patch.object(flow,'transaction_receipt',side_effect=[3_000_000,-11_000_000]), \
                 patch.object(flow,'bridge_token',return_value=({},token)), \
                 patch.object(flow,'owner_balance',return_value=3_000_000), \
                 patch.object(flow,'signer') as signer, \
                 patch.object(flow.time,'time',return_value=456):
                self.assertEqual(flow.cycle(False,'spy')['status'],'BRIDGE_READY')
            self.assertEqual(flow.read_journal(asset)['swap_finalized_at'],456)
            signer.assert_not_called()

    def test_finalized_bridge_records_time_while_x1_receipt_pending(self):
        with tempfile.TemporaryDirectory() as root, patch.object(flow.s, 'ROOT', Path(root)):
            asset=flow.ASSETS['spy']
            row=flow.new_attempt(asset,11_000_000)
            row.update(stage='bridge_pending',swap_signature=str(flow.Signature.default()),
                       bridge_signature=str(flow.Signature.default()),bought_raw=3_000_000,
                       bridge_amount_raw=3_000_000,created_at=100)
            flow.write_attempt(asset,row)
            with patch.object(flow.bridge,'solana_rpc',return_value={'value':[{'confirmationStatus':'finalized','err':None}]}), \
                 patch.object(flow.bridge,'api',return_value={'transaction':{'status':'pending'}}), \
                 patch.object(flow,'signer') as signer, \
                 patch.object(flow.time,'time',return_value=789):
                self.assertEqual(flow.cycle(False,'spy')['status'],'WAITING_FOR_X1_RECEIPT')
            self.assertEqual(flow.read_journal(asset)['bridge_finalized_at'],789)
            signer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
