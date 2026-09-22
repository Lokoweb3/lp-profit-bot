import copy
import unittest
from lp_profit_bot import proceeds as p,seller as s
from lp_profit_bot.stock_policy import STOCKS

class ProceedsTests(unittest.TestCase):
    def token(self,mint,amount,decimals):
        return {'owner':s.WALLET,'mint':mint,'uiTokenAmount':{'amount':str(amount),'decimals':decimals}}
    def tx(self,pre,post,before,after,fee=2507000):
        return {'transaction':{'signatures':['sig'],'message':{'accountKeys':[s.WALLET]}},'blockTime':100,
                'meta':{'err':None,'fee':fee,'preBalances':[before],'postBalances':[after],
                        'preTokenBalances':pre,'postTokenBalances':post}}
    def test_stock_actual_native_proceeds_are_net_of_fee(self):
        mint=STOCKS['spy'].mint
        tx=self.tx([self.token(mint,1000000,8)],[self.token(mint,500000,8)],10000000000,24997493000)
        result=p.decode(tx,{'signature':'sig','amount_raw':500000,'minimum_output_raw':14000000000},'SPY.X',mint)
        self.assertEqual(result['net_xnt_received'],'14.997493')
        self.assertEqual(result['network_fee_xnt'],'0.002507')
        self.assertEqual(result['actual_input'],'0.005')
        self.assertEqual(result['usdc_received'],'0')
    def test_conversion_actual_usdc_and_extra_rent(self):
        tx=self.tx([self.token(s.USDC_MINT,1000000,6)],[self.token(s.USDC_MINT,8500000,6)],40000000000,14995453720)
        result=p.decode(tx,{'signature':'sig','amount_raw':25000000000,'minimum_output_raw':7000000},'XNT',s.WXNT)
        self.assertEqual(result['usdc_received'],'7.5')
        self.assertEqual(result['other_cost_xnt'],'0.00203928')
        self.assertEqual(result['net_xnt_received'],'0')
    def test_direct_googl_sale_actual_output(self):
        tx=self.tx([self.token(s.GOOGL_MINT,1000000,8),self.token(s.USDC_MINT,0,6)],
                   [self.token(s.GOOGL_MINT,500000,8),self.token(s.USDC_MINT,2000000,6)],10000000000,9997493000)
        result=p.decode(tx,{'signature':'sig','amount_raw':500000,'minimum_output_raw':1900000},'GOOGL.X',s.GOOGL_MINT)
        self.assertEqual(result['usdc_received'],'2');self.assertEqual(result['actual_input'],'0.005')
    def test_failed_trade_has_no_proceeds_but_records_fee(self):
        tx=self.tx([],[],10000000000,9997493000);tx['meta']['err']={'InstructionError':[0,'failed']}
        result=p.decode(tx,{'signature':'sig','amount_raw':25000000000,'minimum_output_raw':100},'XNT',s.WXNT)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['actual_input'],'0')
        self.assertEqual(result['usdc_received'],'0');self.assertEqual(result['network_fee_xnt'],'0.002507')
    def test_wrong_signature_or_payer_rejected(self):
        tx=self.tx([],[],10000000000,9997493000)
        row={'signature':'sig','amount_raw':1,'minimum_output_raw':1}
        for field in ('signature','payer'):
            bad=copy.deepcopy(tx)
            if field=='signature':bad['transaction']['signatures']=['wrong']
            else:bad['transaction']['message']['accountKeys']=['wrong']
            with self.assertRaises(s.SellerError):p.decode(bad,row,'XNT',s.WXNT)
