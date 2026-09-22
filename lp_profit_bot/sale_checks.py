"""Recheck executable sale prices immediately before signing."""
import time
from decimal import Decimal


def pre_sign_delta(snapshot, plan, reference, reference_updated, native=True):
    from . import seller
    from .spy_quotes import quote
    from .stock_policy import VALUATION_FACTOR
    reference=Decimal(reference)
    seller.require(reference.is_finite() and reference>0, 'Invalid pre-sign reference')
    seller.require(0<=time.time()-reference_updated<=300, 'Pre-sign reference expired')
    seller.require(0<=time.monotonic()-snapshot['received']<=30, 'Pre-sign pool snapshot expired')
    factor=VALUATION_FACTOR if native else Decimal(1)
    pool=Decimal(snapshot['reserve_out'])/Decimal(snapshot['reserve_in'])*(snapshot['xnt_usd']/10 if native else 100)
    seller.require(pool.is_finite() and pool>0, 'Invalid pre-sign pool price')
    result={'pool_price_usd':str(pool),'reference_price_usd':str(reference),
            'delta_usd':str(pool-reference),'delta_percent':str((pool/reference-1)*100),
            'reference_updated_at':reference_updated,'checked_at':time.time(),'qualifies':False}
    qty=plan['amount_raw']
    if pool<=reference or pool*factor<reference or qty>snapshot['balance_in']:
        return result
    if native:
        current=quote(snapshot,qty)
        output=current['estimated_output_raw'];ending=Decimal(current['ending_pool_price_usd'])
        net_value=Decimal(output-seller.COST_CEILING)/10**9*snapshot['xnt_usd']*factor
    else:
        output,ending=seller.output_for(snapshot,qty)
        net_value=Decimal(output)/10**6-Decimal(seller.COST_CEILING)/10**9*snapshot['xnt_usd']*Decimal('1.05')
    result['qualifies']=(ending*factor>=reference and output>=plan['minimum_output_raw']
                         and net_value>Decimal(qty)/10**8*reference)
    return result
