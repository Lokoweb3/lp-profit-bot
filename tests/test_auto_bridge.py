import unittest
from unittest.mock import patch

from lp_profit_bot import auto_bridge as bridge


class AutoBridgeTests(unittest.TestCase):
    def test_manual_amount_is_bounded_and_exact(self):
        self.assertEqual(bridge.amount_raw('10.000001'), 10_000_001)
        for value in ('9.99','100.000001','10.0000001','bad'):
            with self.assertRaises(bridge.s.SellerError):
                bridge.amount_raw(value)

    def test_manual_preview_shows_fee_and_same_destination(self):
        token={'minAmount':'10000000','maxAmount':'5000000000',
               'dailyCapRemaining':'10000000000','flatFeeAmount':'1000000'}
        with patch.object(bridge,'bridge_config',return_value=({},token)), \
             patch.object(bridge,'wallet_balance',return_value=20_000_000):
            quote=bridge.preview('20')
        self.assertEqual(quote['expected_usdc'],'19')
        self.assertEqual(quote['destination'],bridge.s.WALLET)

    def test_proceeds_excludes_manual_conversion(self):
        conversion = {'entries': [
            {'signature':'automatic', 'status':'finalized', 'source':'stock_proceeds_auto'},
            {'signature':'manual', 'status':'finalized', 'source':'manual'},
        ]}
        sale = {'entries': [{'signature':'googl', 'status':'finalized'}]}
        cache = {
            'automatic': {'signature':'automatic', 'asset':'XNT', 'status':'finalized',
                          'usdc_received':'12.5'},
            'manual': {'signature':'manual', 'asset':'XNT', 'status':'finalized',
                       'usdc_received':'1000'},
            'googl': {'signature':'googl', 'asset':'GOOGL.X', 'status':'finalized',
                      'usdc_received':'2.25'},
        }
        with patch.object(bridge.xnt_conversion, 'read_journal', return_value=conversion), \
             patch.object(bridge.s, 'read_journal', return_value=sale), \
             patch.object(bridge, 'ProceedsHistory') as history:
            history.return_value.cache = cache
            self.assertEqual(bridge.proceeds(), 14_750_000)

    def test_unknown_source_transfer_blocks_another_send(self):
        journal = {'entries':[{'signature':'pending', 'amount_raw':10_000_000,
                               'status':'pending_x1'}]}
        with patch.object(bridge.s, 'rpc', return_value={'value':[None]}):
            self.assertFalse(bridge.reconcile(journal))
            self.assertEqual(journal['entries'][0]['status'], 'pending_x1')

    def test_instruction_targets_same_wallet_route(self):
        tx, outgoing = bridge.build(10_000_000, 80_000_000,
                  '11111111111111111111111111111111', bridge.SYSTEM, bridge.SYSTEM)
        ix = tx.message.instructions[-1]
        self.assertEqual(str(tx.message.account_keys[ix.program_id_index]), bridge.PROGRAM)
        self.assertEqual(bytes(ix.data)[:8], bytes([27,194,57,119,215,165,247,150]))
        self.assertEqual(len(outgoing) > 30, True)


if __name__ == '__main__':
    unittest.main()
