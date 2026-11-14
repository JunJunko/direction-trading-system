"""Research-only, named edits to a frozen strategy. Production modules stay intact.

Every edit is anchored and counted. Weekly direction is read from the frozen
causal event tape, which is invariant under the daily/holding rules tested here.
The unedited path must reproduce the recorded account before comparisons run.
"""
import copy
import inspect
import textwrap
from types import MethodType


VARIANTS = [
    dict(id='baseline',group='baseline',name='冻结基线',rule=None),
    dict(id='E01',group='entry',name='关闭计划前触价消费',rule='preplan_touch'),
    dict(id='E02',group='entry',name='仅关闭确认当根触价消费',rule='confirmation_touch'),
    dict(id='E03',group='entry',name='关闭混合尺度暂停',rule='unresolved_pause'),
    dict(id='E04',group='entry',name='关闭子结构失败暂停',rule='child_pause'),
    dict(id='E05',group='entry',name='关闭最新子结构节奏窗口',rule='rhythm_window'),
    dict(id='E06',group='entry',name='关闭核心实际谷底约束',rule='entry_actual_floor'),
    dict(id='E07',group='entry',name='关闭核心未知顺序终止',rule='core_unknown_order'),
    dict(id='E08',group='entry',name='关闭小结构未知顺序拒绝',rule='small_unknown_order'),
    dict(id='E09',group='entry',name='关闭周线右底起点绑定',rule='direction_origin'),
    dict(id='E10',group='entry',name='关闭核心投射已实现终止',rule='projection_end'),
    dict(id='E11',group='entry',name='关闭核心调整超时终止',rule='core_timeout_end'),
    dict(id='C01',group='control',name='关闭有效压力封顶（敏感性对照）',rule='pressure_cap'),
    dict(id='H01',group='holding',name='关闭日线持仓锚点，恢复小结构锚点',rule='holding_anchor'),
    dict(id='H02',group='holding',name='关闭同级超时预算，恢复时间截短',rule='holding_clock'),
    dict(id='H03',group='holding',name='关闭本级分类准入门槛',rule='holding_level'),
    dict(id='H04',group='holding',name='仅关闭本级幅度门槛',rule='holding_range'),
    dict(id='H05',group='holding',name='仅关闭本级时间门槛',rule='holding_duration'),
    dict(id='H06',group='holding',name='关闭持仓实际谷底约束',rule='holding_actual_floor'),
    dict(id='H07',group='holding',name='关闭持仓上级身份接替退出',rule='holding_upper_owner'),
    dict(id='H08',group='holding',name='关闭持仓未知顺序拒绝',rule='holding_unknown_order'),
]


def edit(source, old, new, count=1):
    if source.count(old)!=count:
        raise ValueError('Frozen source anchor mismatch: '+old[:100])
    return source.replace(old,new)


class FrozenUpper:
    """Only already-observed confirmation/loss events may update direction."""
    def __init__(self,events):
        self.events=events

    def apply(self,strategy,bar):
        state=strategy.states.setdefault(bar.symbol,dict(direction='unknown',processed='',
            pending=None,factor=bar.factor))
        if state.get('floor'):state['floor']*=state['factor']/bar.factor
        state['factor']=bar.factor
        result=copy.deepcopy(self.events.get((bar.symbol,bar.date),[]))
        for event in result:
            assert event['date']==bar.date
            if event['event']=='upper_direction_lost':state['direction']='unknown'
            else:
                source={k:event.get(k) for k in ('first_date','second_date','origin_date',
                    'breakout_date','candidate_id','first_observed_date')}
                state.update(direction='long',floor=float(event['floor']),confirmed_date=bar.date,
                    direction_source=source,retest_started_date=event.get('retest_start_date'))
        return result


def wave_class(module,rule):
    if rule not in ('unresolved_pause','child_pause','entry_actual_floor','core_unknown_order',
                    'projection_end','core_timeout_end'):
        return module.WaveHierarchy
    source=inspect.getsource(module)
    if rule=='unresolved_pause':
        source=edit(source,"else:self.phase='unresolved'\n\n    def _step", 
                    "else:self.phase='recovering' if self.core else 'unresolved'\n\n    def _step")
        source=edit(source,"elif self.core and level=='unresolved':self.phase='unresolved'",
                    "elif False and self.core and level=='unresolved':self.phase='unresolved'")
    elif rule=='child_pause':
        source=edit(source,"self.phase='child_failed_waiting_for_new_floor'\n",
                    "self.phase='recovering'\n")
    elif rule=='entry_actual_floor':
        source=edit(source,"if min(x.low for x in bars[b+1:c+1])<bars[c].low:return None",
                    "if False and min(x.low for x in bars[b+1:c+1])<bars[c].low:return None")
        source=edit(source,"if min(x.low for x in bars[peak+1:low.index+1])<low.price:",
                    "if False and min(x.low for x in bars[peak+1:low.index+1])<low.price:")
    elif rule=='core_unknown_order':
        source=edit(source,"self._end(bars,'order_unknown')","pass  # Diagnostic: observed ambiguity retained, core not terminated")
    elif rule=='projection_end':
        source=edit(source,"elif bars[-1].high>=target:self._end(bars,'projection_consumed')",
                    "elif False and bars[-1].high>=target:self._end(bars,'projection_consumed')")
    elif rule=='core_timeout_end':
        source=edit(source,"if now-peak>ref['correction_duration']+self.right:self._end(bars,'adjustment_timeout')",
                    "if False and now-peak>ref['correction_duration']+self.right:self._end(bars,'adjustment_timeout')")
    namespace=dict(vars(module));exec(compile(source,'<frozen-wave-'+str(rule)+'>','exec'),namespace)
    return namespace['WaveHierarchy']


def entry_method(direction_module,wave_module,rule):
    source=inspect.getsource(direction_module.DirectionDoubleBottom.on_close)
    start=source.index("        if state['direction']!='long':\n",source.index("        if state['direction']!='long':\n") if "        if state['direction']!='long':\n" in source else 0)
    # This condition has exactly one method-level occurrence; candidate-pool
    # direction selection is a different function and is held fixed here.
    body=source[start:]
    if rule=='preplan_touch':
        body=edit(body,"        if nested:\n            observed=lower", "        if False and nested:\n            observed=lower")
    elif rule=='confirmation_touch':
        body=edit(body,"if x.date>=confirmed and x.high>=trigger", "if x.date>confirmed and x.high>=trigger")
    elif rule=='small_unknown_order':
        body=edit(body,"if any(small['a']<=r['index']<=small['c'] for r in cache.ambiguous):",
                  "if False and any(small['a']<=r['index']<=small['c'] for r in cache.ambiguous):")
    elif rule=='direction_origin':
        body=edit(body,"model.get(bars,origin_date=origin)","model.get(bars,origin_date=None)")
    elif rule=='rhythm_window':
        body=edit(body,"core,reason,wave_events=model.get(bars,origin_date=origin)",
            "core,reason,wave_events=model.get(bars,origin_date=origin)\n"+
            "                if core:core=dict(core,rhythm_start_date=bars[core['c']].date,rhythm_floor_date=bars[core['c']].date)")
    elif rule=='pressure_cap':
        body=edit(body,"target=min([core['target']]+pressures)","target=core['target']")
    prefix='''def frozen_entry(self,history,week_ends):
    if not history:return [],[]
    b=adjusted(history[-1:])[0]
    if self.last.get(b.symbol)==b.date:return [],[]
    if self.last.get(b.symbol,'')>b.date:raise ValueError('Noncausal history')
    self.last[b.symbol]=b.date;self.week_ends=week_ends
    events=self.frozen_upper.apply(self,b)
    state=self.states[b.symbol]
'''
    body=textwrap.indent(textwrap.dedent(body),'    ')
    namespace=dict(vars(direction_module));namespace['WaveHierarchy']=wave_class(wave_module,rule)
    exec(compile(prefix+body,'<frozen-entry-'+str(rule)+'>','exec'),namespace)
    return namespace['frozen_entry']


def holding_method(module,rule):
    source=textwrap.dedent(inspect.getsource(module.AutonomousDoubleBottom.manage_live_leg))
    if rule=='holding_anchor':
        source=edit(source,"anchor_date=plan['core_c'] if self.holding_scale_mode=='owned_core' else plan['small_c']",
                    "anchor_date=plan['small_c']")
    elif rule=='holding_clock':
        source=edit(source,"deadline=(plan['live_reference_duration'] if self.holding_scale_mode=='owned_core'",
                    "deadline=(plan['live_reference_duration'] if False")
    elif rule=='holding_actual_floor':
        source=edit(source,"if (self.holding_scale_mode=='owned_core' and measured",
                    "if (False and self.holding_scale_mode=='owned_core' and measured")
    elif rule=='holding_upper_owner':
        source=edit(source,"if (self.p['core_mode']=='nested' and plan.get('upper_owner_id')",
                    "if (False and self.p['core_mode']=='nested' and plan.get('upper_owner_id')")
    elif rule=='holding_level':
        source=edit(source,"if level!='core' or any(anchor<=r['index']<=low.index for r in holding_swings.ambiguous):",
                    "if any(anchor<=r['index']<=low.index for r in holding_swings.ambiguous):")
    elif rule=='holding_unknown_order':
        source=edit(source,"if level!='core' or any(anchor<=r['index']<=low.index for r in holding_swings.ambiguous):",
                    "if level!='core':")
    namespace=dict(vars(module))
    if rule=='holding_range':
        namespace['correction_level']=lambda duration,drop,rd,rp:'core' if duration>=rd else 'internal'
    elif rule=='holding_duration':
        namespace['correction_level']=lambda duration,drop,rd,rp:'core' if drop>=rp else 'internal'
    exec(compile(source,'<frozen-holding-'+str(rule)+'>','exec'),namespace)
    return namespace['manage_live_leg']


def bind_entry(strategy,method,upper):
    strategy.frozen_upper=upper
    def on_close(self,history,ends):
        intents,events=method(self,history,ends)
        for intent in intents:
            intent.evidence.update(core_owner=intent.setup_id,
                core_scale_duration=intent.evidence['correction_duration'],holding_state='verification')
        return intents,events
    strategy.on_close=MethodType(on_close,strategy)
    return strategy


def bind_replay(strategy,tape,upper,holding):
    def on_close(self,history,ends):
        bar=history[-1];self.week_ends=ends;upper.apply(self,bar)
        state=self.states[bar.symbol]
        if state['direction']=='long':
            source=state.get('direction_source',{})
            self.wave_source_ids[bar.symbol]=source.get('candidate_id') or ':'.join(
                str(source.get(k,'')) for k in ('first_date','second_date','breakout_date'))
        new,events=tape.get((bar.symbol,bar.date),([],[]))
        return copy.deepcopy(new),copy.deepcopy(events)
    def begin(self,date):
        return copy.deepcopy(tape.get(('BEGIN',date),([],[]))[1])
    strategy.on_close=MethodType(on_close,strategy)
    strategy.begin_evaluation=MethodType(begin,strategy)
    strategy.manage_live_leg=MethodType(holding,strategy)
    return strategy
