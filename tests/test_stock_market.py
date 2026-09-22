import unittest
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch
from lp_profit_bot.stock_market import fresh_pool_market

class MarketFallbackTests(unittest.TestCase):
    def test_stale_index_uses_verified_reserves(self):
        market={'data_status':'STALE','price_usd':'999','last_synced_at':'old'}
        with patch('lp_profit_bot.spy_quotes.snapshot',return_value={'reserve_in':100000000,'reserve_out':1500000000000,'xnt_usd':Decimal('.3')}) as snapshot:
            result=fresh_pool_market(market,'mint','pool')
        snapshot.assert_called_once_with('mint','pool')
        self.assertEqual(Decimal(result['price_usd']),Decimal('450'))
        self.assertEqual(Decimal(result['liquidity_usd']),Decimal('900'))
        self.assertEqual(result['data_status'],'FRESH')
        self.assertIsNotNone(datetime.fromisoformat(result['last_synced_at']).tzinfo)
        self.assertEqual(market['data_status'],'STALE')

    def test_fresh_index_does_not_require_extra_rpc(self):
        market={'data_status':'FRESH'}
        with patch('lp_profit_bot.spy_quotes.snapshot') as snapshot:
            self.assertIs(fresh_pool_market(market,'mint','pool'),market)
            snapshot.assert_not_called()

    def test_failed_chain_fetch_cannot_mark_stale_price_fresh(self):
        with patch('lp_profit_bot.spy_quotes.snapshot',side_effect=ValueError('unavailable')):
            with self.assertRaises(ValueError):fresh_pool_market({'data_status':'STALE'},'mint','pool')
