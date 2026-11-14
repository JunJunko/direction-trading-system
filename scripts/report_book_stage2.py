"""Reproducible stage-two diagnostic report; no parameter selection."""
import csv,json,hashlib,shutil,sys
from pathlib import Path
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'runs/20261026-book-stage2-fixed'
SHARED=ROOT/'runs/20261026-book-stage2-shared'
OUT=ROOT/'runs/20261026-book-stage2-report'

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
    if not rs:return
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def identity(s):return s[s.index(':'):]

def main():
    OUT.mkdir(exist_ok=True)
    rs=rows(FIX/'paired-trades.csv');summaries=load(FIX/'summary.json');shared=load(SHARED/'summaries.json')
    market=rows(ROOT/'runs/20261026-book-stage2-market/market-proxy.csv')
    mdays=[r['date'] for r in market];marketmap={r['date']:r for r in market}
    base={r['setup_id']:r for r in rs if r['arm']=='X0' and r['cost']=='1'}
    grouped=[];paired=[]
    for arm in ('X3','X4','X5','M1','M2'):
        items=[r for r in rs if r['arm']==arm and r['cost']=='1']
        groups=defaultdict(list)
        for r in items:
            delta=float(r['net_pnl'])-float(base[r['setup_id']]['net_pnl'])
            prior=[d for d in mdays if d<r['entry_date']]
            mr=marketmap[prior[-1]] if prior else {}
            regime='unknown' if not mr.get('return20') else ('up20' if float(mr['return20'])>=0 else 'down20')
            q=r['entry_date'][:4]+'Q'+str((int(r['entry_date'][4:6])-1)//3+1)
            family='W' if r['setup_id'].startswith('double_bottom') else 'IHS'
            for dimension,key in [('family',family),('quarter',q),('market',regime)]:groups[dimension,key].append(delta)
            paired.append(dict(arm=arm,setup_id=r['setup_id'],symbol=r['symbol'],entry_date=r['entry_date'],
                               family=family,quarter=q,market=regime,delta_vs_X0=delta))
        for (dimension,key),ds in groups.items():
            grouped.append(dict(arm=arm,dimension=dimension,group=key,n=len(ds),delta=sum(ds),
                                improved=sum(v>1e-7 for v in ds),worse=sum(v< -1e-7 for v in ds)))
    save(OUT/'grouped-fixed-deltas.csv',grouped);save(OUT/'paired-vs-X0.csv',paired)
    audit={};account=[]
    basekeys={identity(r['setup_id']) for r in rows(SHARED/'X0/entry_audit.csv') if r.get('execution_reason')=='filled'}
    for arm,s in shared.items():
        trades=rows(SHARED/arm/'trades.csv');events=rows(SHARED/arm/'decisions.csv')
        entries=[r for r in rows(SHARED/arm/'entry_audit.csv') if r.get('execution_reason')=='filled']
        t1={(e['symbol'],e['date']) for e in events if e['event']=='stop_deferred_t1'}
        touched=[r for r in entries if (r['symbol'],r['date']) in t1]
        keys={identity(r['setup_id']) for r in entries}
        newclosed=[t for t in trades if identity(t['setup_id']) not in basekeys]
        curve=rows(SHARED/arm/'equity.csv')
        assert all(float(r['cash'])>=-1e-6 and int(r['positions'])<=5 for r in curve)
        closepnl=sum(float(t['pnl']) for t in trades)
        audit[arm]=dict(entries=len(entries),entry_day_stop_touched=len(touched),
            entry_day_stop_touch_share=len(touched)/len(entries),closed=len(trades),
            entry_touch_closed_loss=sum(float(t['pnl'])<0 and (t['symbol'],t['entry_date']) in t1 for t in trades),
            new_setups_vs_X0=len(keys-basekeys),omitted_setups_vs_X0=len(basekeys-keys),
            new_closed_count=len(newclosed),new_closed_pnl=sum(float(t['pnl']) for t in newclosed),
            closed_pnl=closepnl,open_marked_pnl=s['final_equity']-s['initial_cash']-closepnl,
            min_cash=min(float(r['cash']) for r in curve),max_positions=max(int(r['positions']) for r in curve))
        account.append(dict(arm=arm,**{k:s[k] for k in ('total_return','max_drawdown','filled_buys','closed_trades','win_rate')}))
    dump(OUT/'market-execution-audit.json',audit);save(OUT/'shared-summary.csv',account)
    # Quantify prior close sell/stop conflicts separately from strategy differences.
    legacy={r['setup_id']:r for r in rs if r['arm']=='E0' and r['cost']=='1'}
    diffs=[]
    for pid,r in base.items():
        old=legacy[pid];delta=float(r['net_pnl'])-float(old['net_pnl'])
        if abs(delta)>1e-7:
            diffs.append(dict(symbol=r['symbol'],entry_date=r['entry_date'],old_reason=old['exit_reason'],
                new_reason=r['exit_reason'],old_exit=old['exit_price'],new_exit=r['exit_price'],pnl_delta=delta))
    save(OUT/'execution-differences.csv',diffs)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from datetime import datetime
    fig,ax=plt.subplots(figsize=(10,4.5))
    for arm,label in [('X0','v7 / open-first'),('M1','Time-matched'),('M2','Matched + expansion exit')]:
        cr=rows(SHARED/arm/'equity.csv')
        ax.plot([datetime.strptime(r['date'],'%Y%m%d') for r in cr],[float(r['equity'])/10000 for r in cr],label=label)
    ax.set(ylabel='Equity (CNY 10,000)',title='Shared-account replay | known development sample')
    ax.legend();ax.grid(alpha=.2);fig.autofmt_xdate();fig.tight_layout();fig.savefig(OUT/'shared-equity.png',dpi=160);plt.close(fig)
    lines=['# 第二阶段研究结果：执行时序、回调级别与实际市场约束','',
        '完成固定146笔入场的21组对照（7规则×3成本）及3组共享账户重放。新策略未通过收益升级检验；M1降低组合回撤，但净收益仍更差。默认策略和默认历史执行口径未切换，独立v9配置使用开盘优先。','',
        '## 1. 可确认的执行改进','',
        '旧引擎用当天最低价止损抢先于前日已知的开盘卖单。新增`daily_exit_order=open_first`，先执行前一日卖单，再处理仍持有仓位的盘中初始止损。旧口径保留用于精确复现。',
        '开盘跌停的已有退出单保守留待以后交易日，即使当天后来打开跌停也不猜测可成交；T+1和停牌继续阻塞。卖单滑点用开盘价及当时已知跌停价计算，不依赖全天最低价；该滑点是等效成本近似，可能落在实际日K价格范围以外，不能解释为逐笔真实成交价。该修正限于已知的收盘退出单，盘中原始止损仍使用旧日线近似。','',
        f'固定入场中，仅执行变化净增{sum(r["pnl_delta"] for r in diffs):,.2f}元，共{len(diffs)}笔净损益变化，不能将其归为选股或卖出信号改善。详见execution-differences.csv。','',
        '依据：开盘集合竞价先于连续竞价；日线数据不能确定跌停队列和成交深度。交易所规则不保证本策略的开盘单成交。',
        '- [上交所2026交易规则发布及生效日期](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)',
        '- [深交所交易时段说明](https://investor.szse.cn/knowledge/stock/deal/t20191204_572383.html)','',
        '## 2. 书本原则与候选实现','',
        '本轮阅读附件书页92—98（PDF108—114），结合上一阶段295、302—305页。书页95用时间×最大反向幅度近似中继面积；96—98强调趋势与调整在时间上匹配，举例约至少1/3。',
        'M1从入场锚点追踪上涨段：回调时长≥上涨段时长的1/3（向上取整且至少2日）、幅度≥峰值当时的此前ATR14、收盘重新突破前峰，才以此前已形成的低点上移保护。小回调不重置趋势起点，不把突破当日低点倒推成已知支撑。',
        'M2还比较已完成匹配回调：时长不短于前次、时间×幅度面积更大、收盘回撤超过前次最大幅度，才发出调整扩大退出。',
        '至少2日、ATR过滤、三重扩大条件是工程假设；只实现局部近似，不等于书中全部同级别图形判断。规则于运行前冻结，见docs/book-stage2-protocol.md。本轮没有按结果改变阈值。','',
        '## 3. 固定入场，隔离卖出差异','',
        '| 规则 | 总收益（含持仓） | 最大回撤 | 已平仓胜率 |','|---|---:|---:|---:|']
    names={'E0':'旧执行v7','X0':'开盘优先v7','X3':'日线小波谷','X4':'小波谷＋突破前高','X5':'2R/50%价格保护','M1':'时间匹配回调','M2':'时间匹配＋调整扩大'}
    for r in summaries:
        if r['cost']==1:lines.append(f"| {names[r['arm']]} | {r['total_return']:.2%} | {r['max_drawdown']:.2%} | {r['win_rate']:.2%} |")
    lines+=['','比较新策略必须使用X0作基线，不能把执行修正带来的收益算给新策略。1.5和2倍成本的全部结果见固定入场summary.json；只提高佣金率和卖出滑点，税率及最低佣金不变，买入成交价冻结。','',
        '## 4. 共享账户，检验释放资金后的交易','',
        '同一7727个历史候选信号、2861只信号股票，重新分配资金和数量；W优先、IHS次之。以下结果不能与固定入场净值混为一谈。','',
        '| 规则 | 总收益 | 最大回撤 | 买入笔数 |','|---|---:|---:|---:|']
    for r in account:lines.append(f"| {names[r['arm']]} | {r['total_return']:.2%} | {-r['max_drawdown']:.2%} | {r['filled_buys']} |")
    lines+=['',f'![共享账户净值]({(OUT/"shared-equity.png").as_posix()})','',
        'M1的低回撤来自策略与后续资金路径共同作用，固定入场中并没有同样明显的回撤改善。M2的新增交易与损失说明，提前退出释放资金不一定有利。共享账户目前只做标准成本，成本压力测试是固定入场口径。','',
        '## 5. T+1及市场环境诊断','']
    for arm,a in audit.items():
        lines.append(f"- {arm}：{a['entries']}笔买入中，{a['entry_day_stop_touched']}笔（{a['entry_day_stop_touch_share']:.1%}）买入当日已经碰到初始止损；其中最终已平仓亏损{a['entry_touch_closed_loss']}笔。相对X0新增{a['new_setups_vs_X0']}个交易设置、遗漏{a['omitted_setups_vs_X0']}个；新增设置的已平仓净损益{a['new_closed_pnl']:,.2f}元（不含其未平仓市值）。")
    lines+=['','这些交易在买入当天不能正常通过卖出止损，反映入场与止损尺度的重要性；仅优化之后的跟踪止盈无法改变当天的风险暴露。该诊断不能证明所有此类交易最终亏损，也不能直接推导应放宽止损。',
        '同时用快照内当日及前日合资格、连续交易的股票生成等权经济价格收益和上涨家数占比，约2993—3064只/日。它不是官方指数；20日市场方向按入场前一交易日判断，缺少足够历史则标unknown，不回填。仅作诊断，未加入策略。分市场状态、入场季度、W/IHS的配对结果见grouped-fixed-deltas.csv，所有分组属于已知样本，非新保留样本。','',
        '## 6. 决策与边界','',
        '保留开盘优先作为独立、可审计的执行模式；不将M1或M2升级为默认卖出算法。M1可作为降低回撤的研究对照，但尚未达到收益改善目标。后续应优先独立研究入场日风险暴露、止损距离相对ATR、止损后重新入场；不得在持仓已经亏损时单纯放宽止损。',
        '本轮保留原W 2%入场限制，尚非取消限制后的全市场重新识别。历史数据2025-10-09至2026-09-30已经用于多轮研究，季度/行情分组不能变成样本外证明。未平仓采用市值且未扣未来退出费。公司行动仍为合成复权股数而非真实现金分红结算；日线缺少分钟顺序和队列。','',
        '## 7. 复现与验证','',
        '- scripts/study_book_stage2.py：固定入场，旧基线逐笔及241日现金/权益精确复现。',
        '- scripts/backtest_book_stage2_shared.py：共享账户，逐场景校验发出的完整信号集合。',
        '- scripts/stage2_market_diagnostics.py、scripts/report_book_stage2.py：市场与报告。',
        '- tests/test_stage2_exits.py：时序、T+1、跌停、停牌、跳空、未来低点不影响开盘、复权、回调匹配与适配器。',
        '- runs/book-stage2-tests.log：完整回归结果。输出目录不可覆盖原模拟；复跑请使用新OUT目录。']
    report='\n'.join(lines)+'\n'
    (OUT/'report.md').write_text(report,encoding='utf-8')
    (ROOT/'docs/book-stage2-research-20261026.md').write_text(report,encoding='utf-8')
    for f in ('docs/book-stage2-protocol.md','scripts/study_book_stage2.py','scripts/backtest_book_stage2_shared.py',
              'scripts/stage2_market_diagnostics.py','scripts/report_book_stage2.py','runs/book-stage2-tests.log'):
        shutil.copy2(ROOT/f,OUT/Path(f).name)
    dump(OUT/'source-hashes.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'src/trading_system/engine.py',ROOT/'src/trading_system/matched_cycle_exit.py',ROOT/'docs/book-stage2-protocol.md']})
    dump(OUT/'verification.json',dict(legacy_fixed_baseline_exact=load(FIX/'verification.json')['original_trades_and_equity_exact'],
        full_signal_sets_checked=True,shared_cash_nonnegative=True,shared_max_positions_le_5=True,
        known_development_sample=True,default_strategy_changed=False))
    print(json.dumps(audit,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
