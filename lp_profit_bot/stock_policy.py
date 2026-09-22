"""User-approved stock policy. Adding a mint requires explicit authorization."""
from dataclasses import dataclass
from decimal import Decimal

VALUATION_FACTOR = Decimal('0.95')
MINIMUM_QUOTE_FACTOR = Decimal('0.995')

@dataclass(frozen=True)
class Stock:
    key: str
    symbol: str
    mint: str
    pool: str
    reference: str

STOCKS = {
    'aapl': Stock('aapl', 'AAPL.X', 'u7i4awutsHa9qcy6YdDQKfjER16i9fx4PRhG4ZqUXZ5',
                  '4uX1ZyDNVAjpozzsuGMcaHJeSXfpB1TGrckHUkNkB2TX', 'apple-xstock'),
    'spy': Stock('spy', 'SPY.X', '5Z7K1BaM36ubfNHkXbiDm5GW3KGzVSt3DFxD2b7p4VtJ',
                 'C7wzNxd8pa2roCidoP9WcZdnDPRV4TyAyqiotZQzrTFr', 'sp500-xstock'),
    'spcx': Stock('spcx', 'SPCX.X', 'CCqoyVud4QNCccV9EJtWEFPaC6jBaGJsaFTnyD8Ss47m',
                  '7jDUExC8K6WLr2kk8mw7vZN6JwZFCHmcr7qtzFRJ25LX', 'spacex-xstocks'),
    'tsla': Stock('tsla', 'TSLA.X', '47wNUaHJyuiknQswU5qsfYKjaZ9ijueRB63ZrsxuRb4F',
                  '5Ur9GUzt6v9zjL3TSzveVDfZuZMLcfKCMMv9qodj9cZA', 'tesla-xstock'),
    'meta': Stock('meta', 'META.X', '36fxZScbKNXxAfJoiqk76egFGm5b7wWFutjJfXTU5nhT',
                  'Go77gHwGiCMiGuGYWcxvX6sfyQxJhJdbDcqvCbUX131v', 'meta-xstock'),
    'coin': Stock('coin', 'COIN.X', '44QsUuVsKVGk5A1X5Vx7MnevsNe7UTVnijfkbSi3rtpY',
                  'FPvJx6U7qVhgCfaVigjEnVRgn7eHqcR4HMB7RarnhMsR', 'coinbase-xstock'),
    'pltr': Stock('pltr', 'PLTR.X', '2EPkJGy9C4CwdXFc7zpa4VxeansMRcRVdPnR52nBVZbW',
                  '13EhJs5rPcbhrjUBQP6wcxJMqvUrpVLszmu2S32w1VmG', 'palantir-xstock'),
    'amd': Stock('amd', 'AMD.X', '7Y5bai9oWEjZMYMkHxVBUzpUXJqAcwaHi8MptdcDhKk2',
                  '2DHp1qQsjBBhFZ5wupZNkBcs4U1HHKwCVAwqsDCJo46G', 'amd-xstock'),
    'nvda': Stock('nvda', 'NVDA.X', '4JfDXUw8N7b1VJ1og1K3Nc4Z6nwtWxWJUSQKYBcdsiJz',
                  '7TnHuKQc5KEZPqp4NfrzARXpH9XfweVnjyzg1QL7nWs2', 'nvidia-xstock'),
}


def public_policy():
    return {'assets':[stock.symbol for stock in STOCKS.values()], 'total_cap':None,
            'per_trade_cap':None,'valuation_buffer_percent':5,'slippage_percent':0.5,
            'cost_allowance_xnt':'0.01','proceeds':'XNT','auto_convert':'verified stock sale proceeds only',
            'new_deposits_eligible':True}
