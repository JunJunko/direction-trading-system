import unittest
from trading_system.domain import Bar,Position
from trading_system.target_migration import PositionContext,State
from trading_system.strategies.causal_target_w import BaselineClockDecision,CausalTargetW

def b(i,o=11.1,h=11.46,l=11.08,c=11.42):return Bar('X',f'202601{i+1:02}',o,h,l,c,100)
def ctx():return PositionContext('test',0,10,100,9,9,10,11.2)

class CausalTargetTests(unittest.TestCase):
    def test_ordinary_touch_does_not_exit_before_baseline(self):
        d=BaselineClockDecision();c=ctx()
        self.assertIsNone(d.close(c,1,b(1,h=11.3,c=11.1),.25))
        self.assertEqual(c.state,State.PRE_TARGET);self.assertEqual(c.target_touch_at,1)
        self.assertEqual(d.close(c,2,b(2,c=11.21),.25),'target_touch_not_decisive')
        self.assertEqual(c.state,State.EXIT_PENDING)

    def test_candidate_on_baseline_decision_close_allowed(self):
        d=BaselineClockDecision();c=ctx();d.close(c,1,b(1,c=11.1),.25)
        self.assertEqual(d.close(c,2,b(2),.25),'breakout_candidate')
        self.assertEqual(c.target_touch_at,1);self.assertEqual(c.breakout_candidate_at,2)

    def test_queued_exit_cannot_use_future_strength(self):
        d=BaselineClockDecision();c=ctx();d.close(c,1,b(1,c=11.21),.25)
        self.assertIsNone(d.close(c,2,b(2),.25));self.assertEqual(c.state,State.EXIT_PENDING)

    def test_c0_retains_original_close_rule(self):
        d=BaselineClockDecision('hard');c=ctx()
        self.assertIsNone(d.close(c,1,b(1,c=11.1),.25))
        self.assertEqual(d.close(c,2,b(2),.25),'legacy_target_close')

    def test_atr_line_is_not_structural_support_and_effective_next_session(self):
        bars=[b(i,o=10,h=10.2,l=9.8,c=10) for i in range(16)]
        bars.append(b(16))
        s=CausalTargetW('s',dict(target_arm='C4'));s.set_calendar([x.date for x in bars]+['20260118'])
        p=Position('s','X',bars[15].date,10,100,9,110,5,'test',1,dict(w_neckline=10,w_target=11.2))
        exits,events=s.manage_position(bars,p)
        self.assertEqual(exits,[]);self.assertGreater(p.stop,9)
        self.assertEqual(s.contexts['test'].confirmed_support_ids,[])
        changes=[e for e in events if e['reason_code']=='atr_risk_line_changed']
        self.assertEqual(len(changes),1);self.assertEqual(changes[0]['source'],'ATR_RISK')
        self.assertEqual(changes[0]['valid_from_date'],'20260118')

    def test_pure_structure_has_no_atr_protection_before_acceptance(self):
        bars=[b(i,o=10,h=10.2,l=9.8,c=10) for i in range(16)]+[b(16)]
        s=CausalTargetW('s',dict(target_arm='C3'))
        p=Position('s','X',bars[15].date,10,100,9,110,5,'test',1,dict(w_neckline=10,w_target=11.2))
        s.manage_position(bars,p)
        self.assertEqual(p.stop,9);self.assertIsNone(s.risk_lines['test']['atr'])

    def test_atr_contraction_does_not_create_or_move_structural_line(self):
        bars=[b(i,o=10,h=10.2,l=9.8,c=10) for i in range(16)]+[b(16)]
        bars.extend(b(i,o=low+.1,h=low+.4,l=low,c=low+.3) for i,low in enumerate([11.5,11.3,11.28,11.4,11.5,11.6],17))
        s=CausalTargetW('s',dict(target_arm='C3'))
        p=Position('s','X',bars[15].date,10,100,9,110,5,'test',1,dict(w_neckline=10,w_target=11.2))
        for end in range(16,23):s.manage_position(bars[:end],p)
        old=s.risk_lines['test']['structure'];self.assertIsNotNone(old)
        _,events=s.manage_position(bars,p)
        self.assertEqual(s.risk_lines['test']['structure'],old)
        self.assertFalse(any(e['reason_code'] in ('confirmed_support_available','structure_risk_line_changed') for e in events))

    def test_all_prefix_state_and_order_outputs_identical(self):
        bars=[b(i,o=10,h=10.2,l=9.8,c=10) for i in range(16)]+[b(16)]
        bars.extend(b(i,o=low+.1,h=low+.4,l=low,c=low+.3) for i,low in enumerate([11.5,11.3,11.28,11.4,11.5,11.6],17))
        def replay(end):
            s=CausalTargetW('s',dict(target_arm='C4'))
            p=Position('s','X',bars[15].date,10,100,9,110,5,'test',1,dict(w_neckline=10,w_target=11.2))
            outputs=[]
            for count in range(16,end+1):
                ex,events=s.manage_position(bars[:count],p);outputs.append((p.stop,ex,events))
            return outputs
        full=replay(len(bars))
        for end in range(16,len(bars)+1):self.assertEqual(replay(end),full[:end-15])

if __name__=='__main__':unittest.main()
