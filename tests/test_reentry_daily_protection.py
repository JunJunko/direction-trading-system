import unittest
from dataclasses import replace
from unittest.mock import patch
from trading_system.domain import Bar, Position
from trading_system.strategies.reconfirmed_w import ReconfirmedW
from trading_system.strategies.daily_protected_ihs import DailyProtectedIHS
from trading_system.strategies.pressure_support_ihs import PressureSupportIHS
from trading_system.pressure_support_trend import PressureSupportTrend


class ReentryProtectionTests(unittest.TestCase):
    def position(self):
        return Position('test','X','20260101',10.5,100,10.2,40,5,'root',1,
            dict(w_neckline=10.5,w_floor=9,w_target=13,breakout_reference=10.5,
                 w_max_entry_risk=.02,entry_order='next_open'))

    def retry_bars(self):
        return [Bar('X',f'202601{i+3:02d}',10.6,11,low,10.7+i*.02,100)
                for i,low in enumerate([10.2,10.1,10,10.15,10.3])]

    def test_retry_needs_two_confirming_bars_and_is_consumed_once(self):
        strategy=ReconfirmedW('test',{})
        strategy.on_stop_closed(self.position(),'20260102')
        bars=self.retry_bars()
        for count in range(1,5):
            self.assertEqual(strategy.retry_on_close(bars[:count])[0],[])
        intents,_=strategy.retry_on_close(bars)
        self.assertEqual(len(intents),1)
        self.assertEqual(intents[0].stop,10)
        self.assertEqual(intents[0].evidence['retry_confirmed_at'],'20260107')
        self.assertEqual(strategy.retry_on_close(bars)[0],[])
        retry=replace(self.position(),setup_id=intents[0].setup_id,plan=intents[0].evidence)
        self.assertEqual(strategy.on_stop_closed(retry,'20260108'),[])

    def test_target_touch_cancels_before_reentry(self):
        strategy=ReconfirmedW('test',{})
        strategy.on_stop_closed(self.position(),'20260102')
        bars=self.retry_bars();bars[0]=replace(bars[0],high=13)
        intents,events=strategy.retry_on_close(bars)
        self.assertEqual(intents,[])
        self.assertEqual(events[0]['reason'],'target_already_reached')

    def test_retry_price_units_follow_factor(self):
        strategy=ReconfirmedW('test',{})
        strategy.on_stop_closed(self.position(),'20260102')
        bars=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2)
              for b in self.retry_bars()]
        intents,_=strategy.retry_on_close(bars)
        self.assertEqual(intents[0].target,6.5)
        self.assertEqual(intents[0].stop,5)
        self.assertEqual(intents[0].evidence['w_neckline'],5.25)

    def test_daily_higher_low_only_raises_after_confirmation(self):
        strategy=DailyProtectedIHS('test',{})
        manager=PressureSupportTrend('test',[],set())
        strategy.managers['root']=manager
        position=replace(self.position(),entry_date='20260121',stop=9)
        bars=[Bar('X',f'202601{i+1:02d}',10,10.2,9.8,10.1,100) for i in range(20)]
        bars += [Bar('X',f'202601{i+21:02d}',low+.1,low+.3,low,low+.2,100)
                 for i,low in enumerate([10,11.1,11.2,10.8,11.3,11.4])]
        with patch.object(PressureSupportIHS,'manage_position',return_value=([],[])):
            self.assertEqual(strategy.manage_position(bars[:-1],position)[1],[])
            _,events=strategy.manage_position(bars,position)
        self.assertEqual(len(events),1)
        event=events[0]
        self.assertEqual(event['formed'],'20260124')
        self.assertEqual(event['confirmed'],'20260126')
        self.assertEqual(event['effective'],'next_session')
        self.assertGreater(event['new'],position.stop)
        self.assertLess(event['new'],event['daily_low'])


if __name__=='__main__':unittest.main()
