"""Real-hourly contrast on the already fixed daily-proxy diagnosis cohort."""
import argparse,copy,csv,json,os,re,sys,time
from collections import defaultdict,Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ablation_rules import FrozenUpper,entry_method,bind_entry
from audit_reward_risk import read_json,dump,sha


def merge_hourly_session(rows):
    """Preserve the real 09:30 auction by merging it into the 10:30 interval.

    Never reconstruct intraday paths from daily OHLC or use daily extrema to
    repair an incomplete source. Auction volume is additive to the first hour.
    """
    by_time={r['trade_time'][11:19]:dict(r) for r in rows}
    if len(by_time)!=len(rows):raise ValueError('Duplicate hourly timestamps')
    required={'10:30:00','11:30:00','14:00:00','15:00:00'}
    if set(by_time)-required-{'09:30:00'} or not required<=set(by_time):
        raise ValueError('Incomplete/unexpected session timestamps')
    if '09:30:00' in by_time:
        opening=by_time['09:30:00'];first=by_time['10:30:00']
        first.update(open=opening['open'],high=max(first['high'],opening['high']),
            low=min(first['low'],opening['low']),vol=first['vol']+opening['vol'])
    return [by_time[t] for t in sorted(required)]


def research_engine_source(module):
    """Research-only repair of current-hour visibility during warmup."""
    import inspect
    from ablation_rules import edit
    source=inspect.getsource(module)
    source=edit(source,"                for symbol,b in sorted(today.items()):\n",
        "                for bar in lower_by_date.get(date,[]):\n"
        "                    self.lower_histories.setdefault(bar.symbol,[]).append(bar)\n"
        "                for strategy in self.strategies:\n"
        "                    if hasattr(strategy,'set_context'):\n"
        "                        strategy.set_context(dict(self.context,lower_histories=self.lower_histories))\n"
        "                for symbol,b in sorted(today.items()):\n")
    return edit(source,"                for bar in lower_by_date.get(date,[]):\n                    self.lower_histories.setdefault(bar.symbol,[]).append(bar)\n                continue", "                continue")


def main(daily_run,symbols=None):
    daily_run=daily_run.resolve();output=daily_run/('hourly-case-verification' if symbols else 'hourly-verification');output.mkdir(exist_ok=False)
    prior=read_json(daily_run/'evaluation-plan.json');experiment=Path(prior['experiment'])
    frozen=experiment/'frozen-baseline';cohort=set(prior['cohort'])
    if symbols:
        assert set(symbols)<=cohort
        cohort=set(symbols)
    sys.path.insert(0,str(frozen/'source/src'))
    from trading_system.domain import Bar
    from trading_system.data import validate_intraday,save_csv
    from trading_system.engine import Backtest
    from trading_system.universe import MainboardUniverse
    from trading_system.strategies import direction_double_bottom as dm,autonomous_double_bottom as am
    from trading_system import wave_hierarchy as wm
    config=read_json(frozen/'config.json');cal=read_json(frozen/'calendar.json');ud=read_json(frozen/'universe.json')
    plan=dict(created_at=datetime.now().isoformat(),cohort=sorted(cohort),source='Tushare stk_mins 60min over HTTPS',
        source_document='https://tushare.pro/document/2?doc_id=370',
        baseline='Previously reproduced frozen daily-nested entry account',
        changed=['lower_cycle daily_nested -> hourly using actual timestamped bars'],
        fixed=['weekly transition tape','daily core/wave hierarchy','all numeric parameters','target and pressure formula',
               'risk and costs','holding rules','daily order execution and T+1','cohort/calendar/universe'],
        aggregation='Real 09:30 auction merged into first completed hour; no daily-data reconstruction',
        quality='Every supplied complete session must aggregate to frozen daily O/H/L/C and close; abort on mismatches',
        missing='Missing complete hourly days cause no signal for that day, reported explicitly; no imputation',
        selection='600458 low RR, 002708 boundary RR, 002602 passing RR; predetermined daily evidence, no hourly outcome selection' if symbols else prior['selection'],
        account_frequency='Observed account limit 1/minute; sequential 65-second intervals',
        limits=['Previously studied selected-stock sample','Signals still generated at daily close, execution next daily session',
                'This does not verify actual intraday order sequencing or full-market profitability'],production_promoted=False)
    dump(output/'evaluation-plan.json',plan)
    inputs=[frozen/name for name in ('bars.csv','config.json','calendar.json','universe.json','decisions.csv','warmup_decisions.csv')]
    before={str(p.relative_to(experiment)):sha(p) for p in inputs};dump(output/'input-hashes.json',before)
    daily={};bars=[]
    with (frozen/'bars.csv').open(encoding='utf-8-sig',newline='') as stream:
        for r in csv.DictReader(stream):
            if r['symbol'] in cohort:
                b=Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')})
                daily[b.symbol,b.date]=b;bars.append(b)
    rawfolder=output/'raw';rawfolder.mkdir()
    token=os.environ.get('TUSHARE_TOKEN')
    if not token:raise RuntimeError('No configured data credential')
    import requests
    def fetch(symbol):
        params=dict(ts_code=symbol,freq='60min',start_date='2023-01-03 09:00:00',end_date='2026-09-30 15:00:00')
        for attempt in range(3):
            try:
                response=requests.post('https://api.tushare.pro',json=dict(api_name='stk_mins',token=token,params=params,fields=''),timeout=25)
                response.raise_for_status();payload=response.json()
                if payload.get('code')!=0:
                    message=str(payload.get('msg','')).lower()
                    safe_message=re.sub(r'[0-9a-fA-F]{24,}','[redacted]',message.replace(token,'[redacted]'))
                    dump(output/(symbol+'-api-error.json'),dict(code=payload.get('code'),safe_message=safe_message))
                    reason=('frequency_limited' if '频率' in message or '频次' in message else
                            'permission_denied' if '权限' in message or 'permission' in message else 'api_rejected')
                    return symbol,None,reason
                data=payload['data'];records=[dict(zip(data['fields'],items)) for items in data['items']]
                if len(records)>=8000:return symbol,None,'possibly_truncated'
                dump(rawfolder/(symbol+'.json'),records)
                return symbol,records,None
            except Exception:
                if attempt==2:return symbol,None,'transport_failed'
                time.sleep(attempt+1)
    fetched={};failed={}
    for index,symbol in enumerate(sorted(cohort)):
        if index:time.sleep(65)
        symbol,records,error=fetch(symbol)
        if error:failed[symbol]=error
        else:fetched[symbol]=records
        print('Fetched',symbol,len(records) if records else error,'of',len(cohort),flush=True)
        if error=='frequency_limited':break
    dump(output/'fetch-status.json',dict(success=list(sorted(fetched)),failed=failed))
    if failed:raise RuntimeError('Incomplete symbol fetch; recorded semantic errors, no strategy result')
    lower=[];issues=[];missing=[];quality=[]
    for symbol,records in fetched.items():
        sessions=defaultdict(list)
        for r in records:
            date=r['trade_time'][:10].replace('-','')
            if (symbol,date) in daily:sessions[date].append(r)
        for (s,date),b in daily.items():
            if s!=symbol or b.volume<=0:continue
            rs=sessions.get(date,[])
            if not rs:missing.append(dict(symbol=symbol,date=date,reason='missing_session'));continue
            try:hours=merge_hourly_session(rs)
            except ValueError as exc:
                missing.append(dict(symbol=symbol,date=date,reason=str(exc)));continue
            actual=dict(open=hours[0]['open'],high=max(h['high'] for h in hours),
                        low=min(h['low'] for h in hours),close=hours[-1]['close'])
            errors={k:abs(actual[k]-getattr(b,k)) for k in actual}
            if max(errors.values())>1e-5:
                issues.append(dict(symbol=symbol,date=date,daily={k:getattr(b,k) for k in actual},hourly=actual,errors=errors));continue
            for h in hours:
                dt=h['trade_time'].replace('-','').replace(' ','').replace(':','')
                lower.append(Bar(symbol,dt,h['open'],h['high'],h['low'],h['close'],h['vol'],b.factor))
            quality.append(dict(symbol=symbol,date=date,auction_merged=any(r['trade_time'].endswith('09:30:00') for r in rs),max_error=max(errors.values())))
    dump(output/'data-quality.json',dict(complete_sessions=len(quality),missing_sessions=missing,price_mismatches=issues,
        real_hourly_bars=len(lower),auction_sessions=sum(q['auction_merged'] for q in quality)))
    if issues:raise RuntimeError('Hourly/daily price mismatch; no imputation or strategy interpretation')
    validate_intraday(lower);save_csv(output/'hourly.csv',[asdict(b) for b in sorted(lower,key=lambda x:(x.date,x.symbol))])
    upper_events=defaultdict(list)
    for name in ('decisions.csv','warmup_decisions.csv'):
        with (frozen/name).open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                if r['symbol'] in cohort and r['event'] in ('upper_direction_confirmed','upper_direction_lost'):
                    upper_events[r['symbol'],r['date']].append({k:v for k,v in r.items() if v!=''})
    config=copy.deepcopy(config);config['strategies'][0]['params']['lower_cycle']='hourly'
    params=config['strategies'][0]['params'];name=config['strategies'][0]['id']
    # Frozen engine's warmup calls the detector before supplying current hours.
    # Correct this confirmed transport-of-information defect in research only,
    # preserving the frozen production snapshot. Export the exact patched source.
    from trading_system import engine as em
    source=research_engine_source(em)
    namespace=dict(vars(em));exec(compile(source,'<hourly-warmup-information-fix>','exec'),namespace)
    (output/'research-engine.py').write_text(source,encoding='utf-8')
    ResearchBacktest=namespace['Backtest']
    method=entry_method(dm,wm,None)
    strategy=bind_entry(am.AutonomousDoubleBottom(name,params),method,FrozenUpper(upper_events))
    engine=ResearchBacktest(config,[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),lower,
        evaluation_start='20251008',evaluation_end='20261007',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
    plans={}
    for event in engine.events:
        if event['event']=='entry_intent':plans.setdefault(event['setup_id'],event)
    for label,rs in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),
                      ('entry_audit',engine.entry_audits),('decisions',engine.events)]:save_csv(output/(label+'.csv'),rs)
    dump(output/'plans.json',list(plans.values()));summary=engine.summary();dump(output/'summary.json',summary)
    daily_config=copy.deepcopy(config);daily_config['strategies'][0]['params']['lower_cycle']='daily_nested'
    daily_strategy=bind_entry(am.AutonomousDoubleBottom(name,daily_config['strategies'][0]['params']),entry_method(dm,wm,None),FrozenUpper(upper_events))
    baseline_engine=ResearchBacktest(daily_config,[daily_strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),
        evaluation_start='20251008',evaluation_end='20261007',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
    daily_summary=baseline_engine.summary();dump(output/'daily-subcohort-summary.json',daily_summary)
    for label,rs in [('orders',baseline_engine.orders),('trades',baseline_engine.trades),('equity',baseline_engine.curve),('entry_audit',baseline_engine.entry_audits)]:save_csv(output/('daily-'+label+'.csv'),rs)
    after={str(p.relative_to(experiment)):sha(p) for p in inputs};assert before==after,'Frozen input changed'
    result=dict(summary=summary,daily_subcohort_summary=daily_summary,plans=len(plans),first_plan_risk_approved=sum(e['event']=='plan_approved' for e in engine.events),
        net_pnl=summary['final_equity']-summary['initial_cash'],
        entry_wait_reasons=dict(Counter(e.get('reason') for e in engine.events if e['event']=='rhythm_wait')),
        plan_rejection_reasons=dict(Counter(e.get('reason') for e in engine.events if e['event']=='plan_rejected')),
        signal_source='Actual historical hourly data',lower_bars=len(lower),complete_sessions=len(quality),
        missing_sessions=len(missing),price_mismatches=0,cohort_size=len(cohort),
        input_hashes_unchanged=True,production_promoted=False,
        research_warmup_information_fix=True,signal_schedule='daily close -> next daily session')
    dump(output/'result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('daily_run',type=Path);parser.add_argument('--symbols',nargs='+')
    args=parser.parse_args();main(args.daily_run,args.symbols)
