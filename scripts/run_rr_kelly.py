"""Authorized research-only RR sweep; production risk validation remains intact."""
import sys, json, csv, pickle, copy, math, statistics, hashlib, shutil, random
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/20261010-104630-mainboard-double_bottom_v5_11_2-structure'
PRIOR=ROOT/'runs/20261010-140123-double-bottom-rule-ablation'

def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()

def kelly(rs):
    """f is equity risk per INITIAL R, not notional position weight."""
    if not rs or statistics.mean(rs)<=0:return 0.0
    upper=min(.99, min((.99/-r for r in rs if r<0),default=.99))
    derivative=lambda f:sum(r/(1+f*r) for r in rs)
    if derivative(upper)>=0:return upper
    lo=0.
    for _ in range(70):
        mid=(lo+upper)/2
        if derivative(mid)>0:lo=mid
        else:upper=mid
    return (lo+upper)/2

def metrics(ts):
    rs=[float(t['realized_r']) for t in ts];wins=[r for r in rs if r>0];losses=[-r for r in rs if r<0]
    p=len(wins)/len(rs) if rs else None
    w=statistics.mean(wins) if wins else None;l=statistics.mean(losses) if losses else None
    b=w/l if w and l else None
    # Binary approximation is in mean-loss units; divide by mean loss to get initial-R units.
    binary=p-(1-p)/b if b and all(r!=0 for r in rs) else None
    return dict(n=len(rs),win_rate=p,mean_win_r=w,mean_loss_r=l,realized_payoff=b,
        mean_r=statistics.mean(rs) if rs else None,binary_kelly_loss_units=binary,
        binary_kelly_initial_r=binary/l if binary is not None else None,
        empirical_kelly_initial_r=kelly(rs),net_pnl=sum(float(t['pnl']) for t in ts))

def main():
    out=ROOT/'runs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-rr-kelly');out.mkdir()
    grid=[0,.5,.75,1,1.25,1.5,2,2.5,3]
    protocol=dict(grid=grid,protection=['P0','P1'],training_last_exit='20260331',validation_first_entry='20260401',
        end='20260930',seed=20261022,bootstrap=1000,minimum_training_trades=30,
        selection='training mean log(1+f*R), f=min(0.005, empirical Kelly/4); tie: higher RR then P0',
        scope='Previously exposed development data; chronological diagnostic is not independent OOS',
        fixed='Same 35 candidate plans, structural exits/targets, costs, original account sizing and caps',
        risk_override='Research subclass validates all original limits at RR=3 then substitutes authorized nonnegative RR',
        kelly='Full realized R distribution; initial risk fraction, not notional weight. No automatic sizing change.',
        production_promoted=False)
    dump(out/'protocol.json',protocol);shutil.copy2(__file__,out/'source.py')
    inputs=[BASE/n for n in ['bars.csv','config.json','calendar.json','universe.json']]+[PRIOR/'signal-cache.pkl',ROOT/'scripts/research_stage_core.py',ROOT/'scripts/ablation_rules.py']+list((BASE/'source/src').rglob('*.py'))
    hashes={str(p):sha(p) for p in inputs};dump(out/'input-hashes.json',hashes)
    print('OUTPUT '+str(out),flush=True)
    sys.path.insert(0,str(BASE/'source/src'))
    from trading_system import engine as em
    from trading_system.risk import RiskManager
    from trading_system.domain import Bar
    from trading_system.strategies import autonomous_double_bottom as am
    from trading_system.universe import MainboardUniverse
    from trading_system.data import save_csv
    from ablation_rules import FrozenUpper,bind_replay
    from research_stage_core import simple_protection
    from run_rule_ablation import equal_rows
    class ResearchRisk(RiskManager):
        def __init__(self,c):
            if not math.isfinite(c['min_rr']) or c['min_rr']<0:raise ValueError('Invalid experimental RR')
            super().__init__(dict(c,min_rr=3));self.p=copy.deepcopy(c)
    em.RiskManager=ResearchRisk
    cache=pickle.loads((PRIOR/'signal-cache.pkl').read_bytes());symbols={p['symbol'] for p in cache['plans']['baseline'].values()}
    raw=[]
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols and r['date']<='20260930':raw.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    read=lambda n:json.loads((BASE/n).read_text(encoding='utf-8'))
    config=read('config.json');cal=read('calendar.json');ud=read('universe.json');results=[];trades={}
    for protection in ['P0','P1']:
        for rr in grid:
            label=f'{protection}-rr{rr:g}';target=out/label;target.mkdir()
            c=copy.deepcopy(config);c['risk']['min_rr']=rr
            method=am.AutonomousDoubleBottom.manage_live_leg
            if protection=='P1':method=simple_protection(method)
            s=bind_replay(am.AutonomousDoubleBottom(c['strategies'][0]['id'],c['strategies'][0]['params']),cache['tapes']['baseline'],FrozenUpper(cache['upper_events']),method)
            e=em.Backtest(c,[s]).run(raw,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
            if protection=='P0' and rr==3:
                for name,actual in [('orders',e.orders),('trades',e.trades),('equity',e.curve),('entry_audit',e.entry_audits)]:equal_rows(BASE/(name+'.csv'),actual,name)
                dump(out/'baseline-equivalence.json',dict(passed=True))
            for name,actual in [('orders',e.orders),('trades',e.trades),('equity',e.curve),('entry_audit',e.entry_audits)]:save_csv(target/(name+'.csv'),actual)
            train=[t for t in e.trades if t['exit_date']<='20260331'];valid=[t for t in e.trades if t['entry_date']>='20260401']
            m=metrics(train);f=min(.005,m['empirical_kelly_initial_r']/4)
            score=statistics.mean(math.log1p(f*float(t['realized_r'])) for t in train) if train else -1
            valid_log=sum(math.log1p(f*float(t['realized_r'])) for t in valid) if all(1+f*float(t['realized_r'])>0 for t in valid) else None
            row=dict(id=label,rr=rr,protection=protection,full=metrics(e.trades),train=m,validation=metrics(valid),
                train_selected_risk_fraction=f,training_log_score=score,validation_frozen_f_log_sum=valid_log,
                boundary_crossing_trades=len(e.trades)-len(train)-len(valid),summary=e.summary(),open_positions=len(e.positions))
            # Resample entry-month clusters; descriptive only, not multiplicity-adjusted.
            groups={}
            for t in e.trades:groups.setdefault(t['entry_date'][:6],[]).append(float(t['realized_r']))
            rng=random.Random(20261022);keys=sorted(groups);samples=[]
            if len(keys)>=2:
                for _ in range(1000):samples.append(kelly([r for k in rng.choices(keys,k=len(keys)) for r in groups[k]]))
            row['kelly_bootstrap_p05']=sorted(samples)[49] if samples else None
            row['entry_months']=len(keys);results.append(row);trades[label]=e.trades
            dump(target/'summary.json',row);dump(out/'comparison.json',results)
            print(label+' '+json.dumps(row['full']),flush=True)
    best=max(results,key=lambda r:(r['training_log_score'],r['rr'],r['protection']=='P0'))
    eligible=[r for r in results if r['train']['n']>=30 and r['train']['mean_r']>0]
    dump(out/'selection.json',dict(exploratory_training_winner=best['id'],eligible_candidates=[r['id'] for r in eligible],
        deployment_selection=None,reason='Independent validation and adequate training sample required; full-period ranking cannot select parameters',
        validation_note='Frozen training f log sums are trade-distribution diagnostics, not a Kelly-sized account replay; overlapping/capacity constraints remain.'))
    assert all(sha(Path(p))==h for p,h in hashes.items())
    lines=['# 盈亏比门槛与凯利实验','', '18 组参数；最低净盈亏比为严格大于门槛。目标价及结构退出不变。全部为已暴露样本，未更改正式参数。', '',
        '|保护|RR门槛|成交数|胜率|实际平均盈亏比|平均净R|净盈亏|最大回撤|经验凯利*|', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        m=r['full'];b=f"{m['realized_payoff']:.2f}" if m['realized_payoff'] else '—'
        lines.append(f"|{r['protection']}|{r['rr']:g}|{m['n']}|{(m['win_rate'] or 0):.1%}|{b}|{(m['mean_r'] or 0):.3f}|{m['net_pnl']:.2f}|{r['summary']['max_drawdown']:.2%}|{m['empirical_kelly_initial_r']:.1%}|")
    lines+=['','*经验凯利最大化 mean(log(1+fR))，f 是初始止损风险占权益比例，不是股票仓位；仅为样本内估计。负期望取零，无亏损样本触及上限不代表可信仓位。',
        '',f"前半段选择的探索候选：{best['id']}；训练 {best['train']['n']} 笔，后半段 {best['validation']['n']} 笔。达到预设至少 30 笔训练交易的正期望候选：{len(eligible)} 个。",
        '', '分段按训练期已平仓、验证期新开仓划分；跨界交易单独计数。全期账户保持原固定风险，分段有账户路径依赖，不能称独立样本外。详见 comparison.json 和 selection.json。',
        '', '二项凯利 f_loss=p−(1−p)/b；b=平均盈利R/平均亏损R，换算初始风险单位再除平均亏损R。多值盈亏优先使用完整R分布。费用已计入，不拿目标RR替代实际b。',
        '', '方法参考：https://web.stanford.edu/~boyd/papers/kelly.html 及 https://web.stanford.edu/~boyd/papers/robust_kelly.html']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    dump(out/'verification.json',dict(inputs_unchanged=True,baseline_equal=True,production_promoted=False))
    print('COMPLETE '+str(out),flush=True)

if __name__=='__main__':main()
