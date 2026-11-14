"""Run the three registered research workstreams without changing production.

python scripts/run_research_stage.py --fetch-new
python scripts/run_research_stage.py --run <prepared directory>
python scripts/run_research_stage.py --run <directory> --review <export.json>
"""
import argparse
from array import array
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import inspect
import json
import os
from pathlib import Path
import pickle
import shutil
import statistics
import sys
import textwrap
import time
from collections import Counter, defaultdict

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'configs/research/next_stage_v1.json').is_file())
from research_stage_core import (FLAGS, rank, event_from_prefix, match_events,
    path_outcome, summarize_contrast, simple_protection)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(2**20),b''):
            h.update(block)
    return h.hexdigest()


def progress(out, phase, **details):
    state=dict(phase=phase,**details)
    dump(out/'status.json',state)
    print(json.dumps(state,ensure_ascii=True),flush=True)


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        yield from csv.DictReader(stream)


def prepare():
    p=read(ROOT/'configs/research/next_stage_v1.json')
    now=datetime.now(timezone(timedelta(hours=8)))
    out=ROOT/'runs'/f"{p['research_date'].replace('-','')}-{now.strftime('%H%M%S')}-research-stage-v1"
    out.mkdir(exist_ok=False)
    base=ROOT/p['baseline']; prior=ROOT/p['ablation']
    expected=read(prior/'frozen-inputs.json')
    inputs={}
    for name,digest in expected.items():
        file=base/name
        if not file.is_file() or sha(file)!=digest:
            raise ValueError('Frozen baseline mismatch: '+name)
        inputs[str(file)]=digest
    for file in (prior/'signal-cache.pkl',prior/'blind-cases.json',prior/'review-case-map.json',
                 prior/'holding-gate-observations.json',prior/'baseline/plans.json'):
        inputs[str(file)]=sha(file)
    dump(out/'input-hashes.json',inputs)
    source=out/'source';source.mkdir()
    for name in ('run_research_stage.py','research_stage_core.py','research-review.html',
                 'ablation_rules.py','run_rule_ablation.py'):
        shutil.copy2(ROOT/'scripts'/name,source/name)
    shutil.copy2(ROOT/'docs/research-next-stage.md',out/'protocol.md')
    shutil.copy2(ROOT/'configs/research/next_stage_v1.json',out/'protocol.json')
    tests=ROOT/'tests/test_research_stage.py'
    if tests.exists():shutil.copy2(tests,source/tests.name)
    lock={str(f.relative_to(out)):sha(f) for f in [out/'protocol.md',out/'protocol.json',*source.iterdir()] if f.is_file()}
    dump(out/'registration.json',dict(registered_at=now.isoformat(),protocol_locked_before_new_data=True,
        locked_files=lock,baseline_source=str(base/'source/src'),production_promoted=False))
    dump(out/'data-boundary.json',dict(exposed_start='20230103',exposed_end=p['development_end'],
        old_warmup_is_holdout=False,old_evaluation_is_holdout=False,
        new_window_role='first-read external smoke check; insufficient length for validation',
        prospective_start_not_before=p['prospective_start_not_before'],
        required_months=p['minimum_month_blocks'],independent_labels_present=False))
    progress(out,'registered',output=str(out))
    return out


def verify_lock(out):
    for name,digest in read(out/'registration.json')['locked_files'].items():
        if sha(out/name)!=digest:raise ValueError('Registered source drift: '+name)
    # Running the working tool after editing it would otherwise silently violate
    # registration. Frozen copies can be invoked directly for exact replay.
    for name in ('run_research_stage.py','research_stage_core.py','research-review.html'):
        if sha(Path(__file__).parent/name)!=sha(out/'source'/name):
            raise ValueError('Working tool differs from registration: '+name)


def fetch_new(out, p):
    """Bounded HTTPS reads; API messages/credentials never enter reports."""
    target=out/'new-data';target.mkdir(exist_ok=False)
    requests_log=[]
    token=os.environ.get('TUSHARE_TOKEN')
    def fetch(endpoint,params):
        if not token:raise RuntimeError('credential_missing')
        import requests
        response=requests.post('https://api.tushare.pro',json=dict(api_name=endpoint,
            token=token,params=params,fields=''),timeout=25)
        response.raise_for_status()
        payload=response.json()
        code=payload.get('code')
        if code!=0:
            requests_log.append(dict(endpoint=endpoint,params=params,status='api_rejected',code=code))
            raise RuntimeError('api_rejected')
        data=payload['data']
        records=[dict(zip(data['fields'],items)) for items in data['items']]
        if len(records)>=6000:raise RuntimeError('possible_truncation')
        requests_log.append(dict(endpoint=endpoint,params=params,status='ok',rows=len(records)))
        dump(target/(endpoint+'_'+str(len(requests_log))+'.json'),records)
        time.sleep(.4)
        return records
    try:
        # Query calendar first, so an unavailable endpoint fails before any bulk job.
        calendar_end=(datetime.strptime(p['new_data_end'],'%Y%m%d')+timedelta(days=7)).strftime('%Y%m%d')
        cal=fetch('trade_cal',dict(exchange='SSE',start_date=p['new_data_start'],end_date=calendar_end))
        all_dates=sorted(r['cal_date'] for r in cal if int(r['is_open'])==1)
        dates=[d for d in all_dates if d<=p['new_data_end']]
        weeks=defaultdict(list)
        for d in all_dates:weeks[datetime.strptime(d,'%Y%m%d').isocalendar()[:2]].append(d)
        week_ends=[max(ds) for ds in weeks.values() if max(ds)<=p['new_data_end']]
        if not dates:raise RuntimeError('no_new_sessions')
        stocks=[]
        for status in ('L','D','P'):
            stocks.extend(fetch('stock_basic',dict(exchange='',list_status=status)))
        selected={r['ts_code']:r for r in stocks if r.get('market')=='主板'
            and (r['ts_code'].startswith('60') or r['ts_code'].startswith('00'))}
        rows=[];st={}
        for index,day in enumerate(dates):
            daily=fetch('daily',dict(trade_date=day))
            factors={r['ts_code']:r['adj_factor'] for r in fetch('adj_factor',dict(trade_date=day))}
            limits={r['ts_code']:r for r in fetch('stk_limit',dict(trade_date=day))}
            sr=fetch('stock_st',dict(trade_date=day))
            if not daily or not sr:raise RuntimeError('missing_daily_or_st')
            st[day]=[r['ts_code'] for r in sr]
            for r in daily:
                s=r['ts_code']
                if s not in selected:continue
                if s not in factors or s not in limits:raise RuntimeError('incomplete_factor_or_limit')
                rows.append(dict(symbol=s,date=day,open=r['open'],high=r['high'],low=r['low'],close=r['close'],
                    volume=r['vol'],factor=factors[s],up_limit=limits[s]['up_limit'],down_limit=limits[s]['down_limit']))
            progress(out,'fetching_new_data',completed_sessions=index+1,sessions=len(dates))
        dump(target/'extension.json',dict(open_dates=dates,week_ends=week_ends,stocks=list(selected.values()),st_by_date=st,bars=rows))
        status=dict(status='complete',sessions=len(dates),bars=len(rows),requests=requests_log)
    except Exception as error:
        reason=str(error) if isinstance(error,RuntimeError) else type(error).__name__
        status=dict(status='blocked',reason=reason,requests=requests_log,partial_data_used=False)
    dump(target/'fetch-status.json',status)
    dump(target/'hashes.json',{f.name:sha(f) for f in target.glob('*.json')})
    return status


FIELDS=('open','high','low','close','volume','factor','up_limit','down_limit')


def decode(symbol, values):
    from trading_system.domain import Bar
    return [Bar(symbol,str(int(values[i])),*values[i+1:i+9]) for i in range(0,len(values),9)]


def load_compact(base, extension):
    grouped={};count=0
    for r in csv_rows(base/'bars.csv'):
        grouped.setdefault(r['symbol'],array('d')).extend([int(r['date']),*(float(r[k]) for k in FIELDS)])
        count+=1
    if extension:
        for r in extension['bars']:
            grouped.setdefault(r['symbol'],array('d')).extend([int(r['date']),*(float(r[k]) for k in FIELDS)])
    return grouped,count


def upper_replay(raw, ends, params):
    """Extract only the original weekly state machine, anchored before daily gates."""
    from trading_system.strategies import direction_double_bottom as dm
    source=textwrap.dedent(inspect.getsource(dm.DirectionDoubleBottom.on_close))
    anchor="    if state['direction']!='long':"
    if source.count(anchor)!=1:raise ValueError('Weekly extraction anchor drift')
    source=source[:source.index(anchor)]+"    return [], events\n"
    namespace=dict(vars(dm));exec(compile(source,'<registered-weekly-only>','exec'),namespace)
    params={k:v for k,v in params.items() if k not in ('protection_mode','holding_scale_mode')}
    s=dm.DirectionDoubleBottom('weekly-rebuild',params)
    result=[];states={};history=[]
    for b in raw:
        history.append(b)
        _,es=namespace['on_close'](s,history,ends)
        states[b.date]=s.states[b.symbol]['direction']=='long'
        result.extend(e for e in es if e['event'] in ('upper_direction_confirmed','upper_direction_lost'))
    return states,result


def scan(out,p,base,prior,grouped,cal,ud,extension):
    from trading_system.analysis import AdjustedCache
    from trading_system.structure import SwingCache
    from trading_system.universe import MainboardUniverse
    from trading_system.data import validate
    old_ud=copy.deepcopy(ud)
    if extension:
        ud=copy.deepcopy(ud)
        merged={r['ts_code']:r for r in ud['stocks']}
        merged.update({r['ts_code']:r for r in extension['stocks']})
        ud['stocks']=list(merged.values());ud['st_by_date'].update(extension['st_by_date'])
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    old_universe=MainboardUniverse(old_ud['stocks'],old_ud['st_by_date'])
    upper=defaultdict(list)
    for file in ('warmup_decisions.csv','decisions.csv'):
        for r in csv_rows(base/file):
            if r['event'] in ('upper_direction_confirmed','upper_direction_lost'):
                upper[r['symbol'],r['date']].append(r)
    dates=cal['open_dates'];ix={d:i for i,d in enumerate(dates)}
    events=[];counters=Counter();weekly_checks=[]
    params=read(base/'config.json')['strategies'][0]['params']
    start=time.monotonic()
    for index,symbol in enumerate(sorted(grouped)):
        raw=decode(symbol,grouped[symbol])
        raw.sort(key=lambda b:b.date)
        validate(raw)
        ac=AdjustedCache();sw=SwingCache(2,2);history=[];long=False;last_event=-10**9;local=[]
        for b in raw:
            for e in upper.get((symbol,b.date),()):
                long=e['event']=='upper_direction_confirmed'
            history.append(b);known=ac.get(history);points=sw.get(known)
            if b.date < p['development_start']:continue
            eligible=(old_universe if b.date<=p['development_end'] else universe).eligible(symbol,b.date)
            if not eligible or b.volume<=0:
                counters['ineligible_or_no_volume']+=1;continue
            if len(history)<p['minimum_history']:
                counters['insufficient_history_days']+=1;continue
            ev=event_from_prefix(known,points,sw.ambiguous,p)
            if ev is None:continue
            counters['qualified_before_cooldown']+=1
            if ix[b.date]-last_event<p['event_cooldown_sessions']:
                counters['cooldown_excluded']+=1;continue
            last_event=ix[b.date]
            ev['weekly']=long
            ev['partition']='development' if b.date<=p['development_end'] else 'new_smoke'
            local.append(ev)
        if any(e['partition']=='new_smoke' for e in local):
            states,rebuilt=upper_replay(raw,set(cal['week_ends']),params)
            expected=[(day,r['event'],r.get('candidate_id','')) for (sym,day),rows in upper.items() if sym==symbol
                      for r in rows]
            actual=[(e['date'],e['event'],e.get('candidate_id','')) for e in rebuilt if e['date']<=p['development_end']]
            passed=sorted(expected)==sorted(actual)
            weekly_checks.append(dict(symbol=symbol,passed=passed,expected=len(expected),actual=len(actual)))
            if not passed:raise ValueError('Weekly causal rebuild differs from frozen tape: '+symbol)
            for ev in local:
                if ev['partition']=='new_smoke':ev['weekly']=states[ev['date']]
        events.extend(local)
        if index%100==0 or index+1==len(grouped):
            progress(out,'building_opportunity_cohort',symbols_done=index+1,symbols=len(grouped),events=len(events),
                elapsed_seconds=round(time.monotonic()-start))
    dump(out/'events.json',events)
    dump(out/'cohort-audit.json',dict(counters=dict(counters),events=len(events),symbols=len(grouped),
        weekly_rebuild_checks=weekly_checks,selection_uses_future=False,original_strategy_equivalence=False))
    return events


def materialize_outcomes(events,grouped,cal,p):
    by_symbol=defaultdict(list)
    for event in events:by_symbol[event['symbol']].append(event)
    outcomes={}
    old_dates=[d for d in cal['open_dates'] if d<=p['development_end']]
    for symbol,items in by_symbol.items():
        raw={b.date:b for b in decode(symbol,grouped[symbol])}
        for event in items:
            window=old_dates if event['partition']=='development' else cal['open_dates']
            outcomes[event['event_id']]=path_outcome(event,raw,window,p['horizons'])
    return outcomes


def protection(out,p,base,prior,grouped):
    from ablation_rules import bind_replay,FrozenUpper
    from run_rule_ablation import equal_rows
    from trading_system.strategies import autonomous_double_bottom as am
    from trading_system.engine import Backtest
    from trading_system.universe import MainboardUniverse
    from trading_system.data import save_csv
    cache=pickle.loads((prior/'signal-cache.pkl').read_bytes())
    plans=cache['plans']['baseline'];symbols={v['symbol'] for v in plans.values()}
    raw=[b for s in sorted(symbols) for b in decode(s,grouped[s]) if b.date<=p['development_end']]
    config=read(base/'config.json');cal=read(base/'calendar.json');ud=read(base/'universe.json')
    results=[]
    for variant in ('P0','P1'):
        target=out/variant;target.mkdir(exist_ok=False)
        original=am.AutonomousDoubleBottom.manage_live_leg
        method=original if variant=='P0' else simple_protection(original)
        strategy=bind_replay(am.AutonomousDoubleBottom(config['strategies'][0]['id'],config['strategies'][0]['params']),
            cache['tapes']['baseline'],FrozenUpper(cache['upper_events']),method)
        engine=Backtest(copy.deepcopy(config),[strategy]).run(raw,cal['open_dates'],set(cal['week_ends']),
            evaluation_start=p['development_start'],evaluation_end=p['development_end'],
            universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
        if variant=='P0':
            for name,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
                equal_rows(base/(name+'.csv'),actual,name)
            dump(out/'baseline-equivalence.json',dict(passed=True,plans=len(plans),
                checked=['every order','every trade','daily account equity','entry assessment']))
        for name,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits),('decisions',engine.events)]:
            save_csv(target/(name+'.csv'),actual)
        summary=engine.summary();promotions=[e for e in engine.events if e['event'] in ('core_protection_promoted','diagnostic_protection_promoted')]
        trades=engine.trades
        result=dict(variant=variant,summary=summary,net_pnl=summary['final_equity']-summary['initial_cash'],
            promotion_count=len(promotions),mean_net_r=statistics.mean(t['realized_r'] for t in trades) if trades else None,
            best_net_r=max((t['realized_r'] for t in trades),default=None),
            closed_trade_count=len(trades),candidate_plans=len(plans),
            exposure_days=sum(r['positions']>0 for r in engine.curve),
            mean_gross_weight=statistics.mean(r['gross_weight'] for r in engine.curve),
            scope='development-only joint protection diagnostic; not independent validation')
        dump(target/'summary.json',result);dump(target/'promotions.json',promotions)
        results.append(result)
        progress(out,'protection_comparison',variant=variant,trades=len(trades),promotions=len(promotions))
    dump(out/'protection-comparison.json',results)
    return results


def blind_package(out,p,prior,events,grouped):
    from trading_system.analysis import adjusted
    old=read(prior/'blind-cases.json');old_map=read(prior/'review-case-map.json')
    cases=[];mapping=[];strata=defaultdict(list)
    for e in events:
        if e['partition']=='development':strata[tuple(e[k] for k in FLAGS)].append(e)
    for flags,items in sorted(strata.items()):
        for e in sorted(items,key=lambda x:rank(x['event_id'],p['seed']))[:p['blind_cases_per_stratum']]:
            raw=decode(e['symbol'],grouped[e['symbol']])
            known=adjusted([b for b in raw if b.date<=e['date']])
            indices={b.date:i for i,b in enumerate(known)}
            start=max(0,min(indices[e['a']]-10,len(known)-100))
            shown=known[start:];ix={b.date:i for i,b in enumerate(shown)}
            line=[dict(label=k.upper(),date=e[k],i=ix[e[k]],y=getattr(shown[ix[e[k]]],'high' if k=='b' else 'low')) for k in ('a','b','c')]
            panel=dict(cycle='日线候选结构',bars=[dict(date=b.date,o=b.open,h=b.high,l=b.low,c=b.close) for b in shown],
                line=line,levels=[],marks=[dict(date=e['date'],label='观察日')])
            cid=f'N{len(cases)+1:03d}'
            cases.append(dict(case_id=cid,kind='entry',as_of=e['date'],panels=[panel],previously_reviewed=False))
            mapping.append(dict(case_id=cid,event_id=e['event_id'],symbol=e['symbol'],flags=dict(zip(FLAGS,flags)),source='new_cohort'))
    for c in old:
        copied={k:copy.deepcopy(v) for k,v in c.items() if k not in ('symbol','core_confirmed','small_confirmed')}
        copied['case_id']='R'+c['case_id'];copied['previously_reviewed']=True
        copied.setdefault('kind','entry');cases.append(copied)
        mapping.append(dict(case_id=copied['case_id'],symbol=c['symbol'],source='reused_prior_cases',
            prior=[m for m in old_map if m['case_id']==c['case_id']]))
    cases.sort(key=lambda x:rank(x['case_id'],p['seed']))
    for c in cases:
        for panel in c['panels']:
            if any(b['date']>c['as_of'] for b in panel['bars']):raise ValueError('Future bar in review')
    dump(out/'blind-cases.json',cases);dump(out/'review-case-map-private.json',mapping)
    payload=json.dumps(cases,ensure_ascii=False).replace('</','<\\/')
    template=(out/'source/research-review.html').read_text(encoding='utf-8')
    page=template.replace('__CASES__',payload).replace('__RUN__',out.name).replace('__HASH__',sha(out/'blind-cases.json'))
    (out/'blind-review.html').write_text(page,encoding='utf-8')
    dump(out/'review-status.json',dict(cases=len(cases),new_cases=sum(not c['previously_reviewed'] for c in cases),
        reused_cases=len(old),independent_labels=0,status='awaiting_independent_review',
        future_bars_present=False,review_page_includes_outcomes=False,automated_checks_are_ground_truth=False))


def import_review(out,path):
    data=read(path);cases={c['case_id']:c for c in read(out/'blind-cases.json')}
    if data.get('run')!=out.name or data.get('case_hash')!=sha(out/'blind-cases.json'):
        raise ValueError('Review belongs to different cases or run')
    if not data.get('reviewer','').strip():raise ValueError('Reviewer name required')
    allowed={'yes','no','unclear',''};valid=[]
    for cid,label in data.get('labels',{}).items():
        if cid not in cases:raise ValueError('Unknown case id')
        if label.get('as_of')!=cases[cid]['as_of']:raise ValueError('Wrong case observation date')
        if any(label.get(k,'') not in allowed for k in ('structure','ownership','timing')):raise ValueError('Invalid label')
        if all(label.get(k) in ('yes','no','unclear') for k in ('structure','ownership','timing')):
            valid.append(cid)
    target=out/'reviews';target.mkdir(exist_ok=True)
    digest=sha(path);destination=target/(digest+'.json')
    if not destination.exists():shutil.copy2(path,destination)
    all_reviews=[read(f) for f in target.glob('*.json')]
    independent=[r for r in all_reviews if r.get('independent') is True]
    dump(out/'review-import.json',dict(imported_files=len(all_reviews),completed_in_this_file=len(valid),
        independent_reviewer_attestations=len({r['reviewer'] for r in independent}),
        independent_status='self_attested_not_verified',ground_truth_accuracy_not_claimed=True))
    print(json.dumps(dict(review_imported=True,completed=len(valid)),ensure_ascii=True))


def report(out,p,contrasts,protections,fetch_status):
    def fmt(x):return '—' if x is None else f'{x:.3f}'
    rows=[]
    labels={'weekly':'周线双底方向 W','zone':'历史高点区域 Z','trigger':'当日恢复触发 T'}
    for partition,summary in contrasts.items():
        for c in summary:
            interval=c['month_cluster_interval']
            rows.append(f"|{partition}|{labels[c['flag']]}|{c['treated']}|{c['pairs']}|{c['complete_pairs']}|{fmt(c['mean_difference_atr'])}|{str([round(x,3) for x in interval]) if interval else '—'}|{c['month_blocks']}|")
    protection_rows=[f"|{r['variant']}|{r['closed_trade_count']}|{r['net_pnl']:.2f}|{fmt(r['mean_net_r'])}|{r['summary']['max_drawdown']:.2%}|{r['promotion_count']}|" for r in protections]
    review=read(out/'review-status.json')
    lines=['# 下一阶段研究结果（开发样本诊断）','',
        '本轮固定协议后运行。价格路径对照不是可执行收益；两个保护版本仍在同一已研究样本上比较。未晋升任何策略。','',
        '## 工作状态','',f"- 结构与保护：已生成{review['cases']}例审核包，其中新增{review['new_cases']}例、复用{review['reused_cases']}例；独立人工标签仍待输入。P0/P1账户对照已完成。",
        '- 优势来源：独立日线N机会池、同日条件匹配及20日价格路径对照已完成；只衡量注册条件的关联增量。',
        f"- 独立数据：新增接口状态为 `{fetch_status['status']}`。正式前瞻边界不早于{p['prospective_start_not_before']}；目前没有足够的独立长期证据。",'',
        '## 保护对照','', '|版本|平仓数|账户净盈亏（元）|平均净R|最大回撤|保护上移次数|','|---|---:|---:|---:|---:|---:|',*protection_rows,'',
        'P0逐项复现原委托、交易、每日权益和入场审核。P1只新增确认日线谷底的简单保护，不改变上级/超时退出、费用、风险预算或候选入场计划；更早退出可以改变后续实际成交及仓位。单笔峰值不是可执行卖点，2笔基线成交不足以选优。','',
        '## 条件对照','', '|数据分区|条件|有条件事件|配对数|完整终点配对|20日差值/ATR|月份块95%探索区间|月份数|',
        '|---|---|---:|---:|---:|---:|---|---:|',*rows,'',
        '差值为条件存在组减匹配对照组。匹配固定同日、交易所、另外两个条件，并控制20日涨幅、相对波动和成交额。未观测混杂仍存在，不能推断因果。月份区间、标的聚类敏感性、匹配平衡、缺失终点及截尾敏感性详见contrasts.json。多个条件属于同一实验族，不选取最好看的单项宣称成功。','',
        '## 数据与下一步','',
        '旧快照（含预热）全部登记为已暴露。新增窗口即便取数成功，也需等20日终点与至少12个信号月份成熟。审核人完成blind-review.html并导出后，可用脚本--review导入；脚本不会伪造独立标签。',
        '通过信息层后还需另外注册统一执行/退出的组合实验。当前P1收益变化和价格路径关联都不能代替该验证。','',
        '文件：protocol.md、registration.json、input-hashes.json、baseline-equivalence.json、events.json、pairs.json、outcomes.json、contrasts.json、protection-comparison.json、review-status.json、data-boundary.json。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Simple self-contained report: data tables plus explicit stage boundaries.
    body='<h1>下一阶段研究</h1><p>开发样本诊断 · 尚无独立长期有效性结论</p><p><a href="blind-review.html">进入结构与保护盲审</a> · <a href="report.md">完整研究记录</a> · <a href="protocol.md">事前协议</a></p>'
    body+='<h2>保护对照</h2><table><tr><th>版本</th><th>平仓</th><th>净盈亏</th><th>平均净R</th><th>保护上移</th></tr>'
    for r in protections:body+=f"<tr><td>{r['variant']}</td><td>{r['closed_trade_count']}</td><td>{r['net_pnl']:.2f}</td><td>{fmt(r['mean_net_r'])}</td><td>{r['promotion_count']}</td></tr>"
    body+='</table><h2>价格路径条件对照</h2><p>单位为固定信号ATR；不是成交净收益。所有区间为探索性结果。</p><table><tr><th>分区/条件</th><th>配对/完整</th><th>20日差值</th><th>月份区间</th></tr>'
    for partition,summary in contrasts.items():
        for c in summary:body+=f"<tr><td>{html.escape(partition+' / '+labels[c['flag']])}</td><td>{c['pairs']} / {c['complete_pairs']}</td><td>{fmt(c['mean_difference_atr'])}</td><td>{html.escape(str(c['month_cluster_interval']))}</td></tr>"
    body+=f"</table><h2>未完成的证据</h2><p>{review['cases']}例已准备；独立审核待输入。新增数据：{html.escape(fetch_status['status'])}。前瞻验证从不早于{p['prospective_start_not_before']}开始，尚需足够月份和成熟终点。</p>"
    (out/'report.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>下一阶段研究</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.8 system-ui;color:#233043;background:#f5f7fa}table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce3ed}a{color:#215fbd}h2{margin-top:35px}</style>'+body+'</html>',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run');parser.add_argument('--fetch-new',action='store_true')
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--review')
    parser.add_argument('--replay-from',help='Verified same-protocol cohort and new-data snapshot; re-lock pairs before endpoint arithmetic')
    args=parser.parse_args();out=Path(args.run).resolve() if args.run else prepare()
    verify_lock(out)
    if args.review:return import_review(out,Path(args.review))
    if args.prepare_only:return
    if (out/'events.json').exists():raise ValueError('Completed/partial research outputs exist; use a fresh registration')
    p=read(out/'protocol.json');base=ROOT/p['baseline'];prior=ROOT/p['ablation']
    sys.path.insert(0,str(base/'source/src'))
    replay=Path(args.replay_from).resolve() if args.replay_from else None
    if replay and args.fetch_new:raise ValueError('Choose replay or fetch, not both')
    if replay:
        if read(replay/'protocol.json')!=p:raise ValueError('Replay protocol differs')
        if sha(replay/'source/research_stage_core.py')!=sha(out/'source/research_stage_core.py'):
            raise ValueError('Replay feature/matching/endpoint definitions changed')
        recorded=read(replay/'artifact-hashes.json')
        for name in ('events.json','pairs.json','outcomes.json','cohort-audit.json'):
            if sha(replay/name)!=recorded[name]:raise ValueError('Replay artifact changed: '+name)
        for name,digest in read(replay/'new-data/hashes.json').items():
            if sha(replay/'new-data'/name)!=digest:raise ValueError('Replay data changed: '+name)
        shutil.copytree(replay/'new-data',out/'new-data')
        fetch_status=read(out/'new-data/fetch-status.json')
        dump(out/'technical-replay.json',dict(prior_run=str(replay),
            original_registration=read(replay/'registration.json')['registered_at'],
            reason='Enforce persisted matching before endpoint arithmetic; original matching already accepted no outcomes.',
            signal_matching_endpoint_definitions_unchanged=True,first_read_data_origin=str(replay/'new-data'),
            selection_source='hash-verified same-rule full-population cohort'))
    elif args.fetch_new:
        fetch_status=fetch_new(out,p)
    else:
        fetch_status=dict(status='not_requested',independent_validation=False)
        dump(out/'new-data-status.json',fetch_status)
    extension=read(out/'new-data/extension.json') if fetch_status['status']=='complete' else None
    grouped,count=load_compact(base,extension)
    if count!=2856672:raise ValueError('Unexpected baseline population')
    cal=read(base/'calendar.json');ud=read(base/'universe.json')
    if extension:
        cal['open_dates']=sorted(set(cal['open_dates'])|set(extension['open_dates']))
        # Future calendar metadata establishes week completion; no future prices.
        cal['week_ends']=sorted(set(cal['week_ends'])|set(extension['week_ends']))
    protections=protection(out,p,base,prior,grouped)
    if replay:
        events=read(replay/'events.json');dump(out/'events.json',events)
        shutil.copy2(replay/'cohort-audit.json',out/'cohort-audit.json')
    else:
        events=scan(out,p,base,prior,grouped,cal,ud,extension)
    pairs={};contrasts={}
    for partition in ('development','new_smoke'):
        cohort=[e for e in events if e['partition']==partition]
        pairs[partition]={};contrasts[partition]=[]
        for flag in FLAGS:
            matches=match_events(cohort,flag,p);pairs[partition][flag]=matches
    dump(out/'pairs.json',pairs)
    order=dict(pair_lock_time=datetime.now(timezone(timedelta(hours=8))).isoformat(),pairs_sha256=sha(out/'pairs.json'))
    dump(out/'execution-order.json',order)
    outcomes=materialize_outcomes(events,grouped,cal,p)
    dump(out/'outcomes.json',outcomes)
    order['outcomes_completed_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
    order['pairs_unchanged']=sha(out/'pairs.json')==order['pairs_sha256']
    if replay:
        order['same_pairs_as_prior']=pairs==read(replay/'pairs.json')
        order['same_endpoints_as_prior']=outcomes==read(replay/'outcomes.json')
        if not order['same_pairs_as_prior'] or not order['same_endpoints_as_prior']:
            raise ValueError('Technical ordering replay changed research results')
    dump(out/'execution-order.json',order)
    for partition in pairs:
        cohort=[e for e in events if e['partition']==partition]
        contrasts[partition]=[summarize_contrast(cohort,pairs[partition][flag],outcomes,flag,p) for flag in FLAGS]
    dump(out/'contrasts.json',contrasts)
    blind_package(out,p,prior,events,grouped)
    report(out,p,contrasts,protections,fetch_status)
    for name,digest in read(out/'input-hashes.json').items():
        if sha(name)!=digest:raise ValueError('Input changed during research: '+name)
    verify_lock(out)
    dump(out/'verification.json',dict(baseline_equal=True,inputs_unchanged=True,protocol_unchanged=True,
        independent_labels_complete=False,independent_long_term_validation=False,
        production_promoted=False,review_has_future_bars=False))
    dump(out/'artifact-hashes.json',{str(f.relative_to(out)):sha(f) for f in out.rglob('*') if f.is_file() and f.name!='artifact-hashes.json'})
    progress(out,'completed_with_pending_evidence',output=str(out),events=len(events),
        pending=['independent structure labels','mature independent long-term sample'])


if __name__=='__main__':main()
