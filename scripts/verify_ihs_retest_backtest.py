"""Verify v3 causal retests and compare with the prior right-shoulder account."""
import csv,gzip,hashlib,html,json,math,shutil,sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'
OLD=ROOT/'runs/20261025-ihs-head-vs-right-shoulder'
V2=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v2'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    manifest,plans,summary,config=(load(OUT/n) for n in ('manifest.json','plans.json','summary.json','config.json'))
    before=load(OLD/'right_shoulder/summary.json');baseconfig=load(OLD/'config.json')
    assert {k:v for k,v in config.items() if k!='strategies'}=={k:v for k,v in baseconfig.items() if k!='strategies'}
    assert manifest['bars_sha256']==load(V2/'manifest.json')['bars_sha256']==sha(OUT/'bars.csv')
    assert manifest['universe_sha256']==load(V2/'manifest.json')['universe_sha256']
    assert manifest['config_sha256']==sha(OUT/'config.json')
    digest=hashlib.sha256()
    for p in sorted((OUT/'source/src').rglob('*.py')):
        digest.update(str(p.relative_to(OUT/'source/src')).encode());digest.update(p.read_bytes())
    assert digest.hexdigest()==manifest['code_sha256']
    # Registration must preserve v2 layouts; the new state machine only delays entry.
    registered={};counts=Counter();invalidations=Counter();seed_count=0
    for path in (OUT/'signal-events').glob('*.gz'):
        seed_count+=1
        with gzip.open(path,'rt',encoding='utf-8') as f:
            for line in f:
                e=json.loads(line)
                if e['event']=='ihs_retest_registered':registered[e['setup_id']]=e
                if manifest['evaluation_start']<=e['date']<=manifest['evaluation_end']:
                    counts[e['event']]+=1
                    if e['event']=='ihs_retest_invalidated':invalidations[e['reason']]+=1
    oldplans=load(V2/'plans.json')
    assert counts['ihs_retest_registered']==len(oldplans)==2925
    for p in oldplans:
        pid=p['setup_id'].replace('inverse_head_shoulders_v2_enclosing:','inverse_head_shoulders_v3_retest:',1)
        seed=registered[pid]
        for k in ('date','trigger','stop','target','ihs_left_date','ihs_head_date','ihs_right_date'):
            assert seed[k]==p[k],(pid,k)
    needed={p['symbol'] for p in plans};lookup={};hist={s:[] for s in needed}
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed:
                hist[r['symbol']].append(r);lookup[r['symbol'],r['date']]=r
    rules=config['strategies'][0]['params'];checks=[]
    for p in plans:
        seed=registered[p['setup_id']]
        assert seed['date']==p['ihs_known_at']<p['ihs_retest_date']<=p['date']==p['ihs_retest_confirmed']
        b=lookup[p['symbol'],p['date']];factor=float(b['factor'])
        price=lambda r,k:float(r[k])*float(r['factor'])/factor
        previous=sorted((r for r in hist[p['symbol']] if r['date']<p['date']),key=lambda r:r['date'])[-1]
        right=lookup[p['symbol'],p['ihs_right_date']];head=lookup[p['symbol'],p['ihs_head_date']]
        assert math.isclose(price(right,'low'),p['stop'],rel_tol=1e-12)
        assert math.isclose(price(head,'low'),p['ihs_floor'],rel_tol=1e-12)
        assert math.isclose(p['target'],2*p['ihs_neckline']-p['ihs_floor'],rel_tol=1e-12)
        after=[r for r in hist[p['symbol']] if p['ihs_known_at']<r['date']<=p['date']]
        assert len(after)<=rules['retest_sessions']
        low=min(price(r,'low') for r in after)
        assert math.isclose(low,p['ihs_retest_low'],rel_tol=1e-12)
        assert low<=p['ihs_neckline']*(1+rules['touch_tolerance'])
        assert low>=p['ihs_neckline']*(1-rules['failure_tolerance'])
        assert low>p['stop']
        assert max(price(r,'high') for r in after)<p['target']
        assert p['ihs_neckline']<p['trigger']<=p['ihs_entry_ceiling']
        assert float(b['close'])>max(float(b['open']),price(previous,'close'))
        checks.append(dict(setup_id=p['setup_id'],breakout_known=p['ihs_known_at'],
            retest_date=p['ihs_retest_date'],confirmed=p['date'],sessions=len(after)))
    audits=rows(OUT/'entry_audit.csv');filled=[a for a in audits if a.get('execution_reason')=='filled']
    pm={p['setup_id']:p for p in plans}
    for a in filled:
        p=pm[a['setup_id']];b=lookup[a['symbol'],a['date']]
        scale=p['factor']/float(b['factor'])
        assert float(b['open'])>=p['ihs_neckline']*scale
        assert float(a['fill'])<=p['ihs_entry_ceiling']*scale+1e-12
        assert float(a['net_rr'])>3 and a['signal_date']<a['date']
        assert math.isclose(float(a['fill']),float(b['open'])*1.001,rel_tol=1e-12)
    curve=rows(OUT/'equity.csv');assert len(curve)==241
    peak=config['initial_cash'];dd=0
    for r in curve:
        value=float(r['equity']);peak=max(peak,value);dd=min(dd,value/peak-1)
        assert math.isclose(float(r['drawdown']),value/peak-1,abs_tol=1e-12)
    assert math.isclose(dd,summary['max_drawdown'],abs_tol=1e-12)
    assert float(curve[-1]['equity'])==summary['final_equity']
    assert len(filled)==summary['filled_buys']
    verification=dict(status='passed',all_3214_tapes_read=seed_count==3214,
        same_2925_breakout_registrations=True,all_retest_signals_verified=len(plans),
        all_filled_entries_hold_neckline=True,filled_verified=len(filled),equity_rows_verified=241,
        config_and_source_hash_verified=True,scope='same snapshot and account; right-shoulder stop and measured target unchanged')
    dump(OUT/'retest-verification.json',verification)
    outcomes=Counter(a.get('execution_reason') for a in audits)
    dump(OUT/'v2-v3-comparison.json',dict(breakout_right_shoulder=before,retest=summary,
        event_counts=dict(counts),retest_invalidations=dict(invalidations),entry_audit_outcomes=dict(outcomes),verification=verification))
    def fmt(k,v):
        if v is None:return '无样本'
        if k in ('total_return','max_drawdown','win_rate'):return f'{abs(v) if k=="max_drawdown" else v:.2%}'
        return str(v)
    table='<table><tr><th>指标</th><th>v2 突破买入＋右肩止损</th><th>v3 回踩确认＋右肩止损</th></tr>'
    for label,key in [('成交','filled_buys'),('平仓','closed_trades'),('期末持仓','open_positions'),('收益率','total_return'),('最大回撤','max_drawdown'),('平仓胜率','win_rate')]:
        table+=f'<tr><td>{label}</td><td>{fmt(key,before[key])}</td><td>{fmt(key,summary[key])}</td></tr>'
    table+='</table>'
    extra='<h2>与突破买入对照</h2>'+table+f'<p>同样的 2,925 个考核区间突破登记已逐项核对，v3 经等待与回踩确认生成 {len(plans)} 个入场信号。两组买点不同，不能将收益差异简单归因于胜率变化；股数与账户后续占用随入场变化。</p>'
    extra+='<p>每笔信号已核验突破登记、后续回踩、收盘回升、右肩止损与等距目标；所有实际成交开盘守住颈线且未超过入场上限。241 根净值与回撤独立重算通过。<a href="retest-verification.json">核验记录</a> · <a href="v2-v3-comparison.json">完整对照</a>。</p>'
    extra+='<h2>等待与执行诊断</h2><p>失效原因按发生日统计，可能包括考核前登记的形态；期末尚在等待的形态不计失效，因此不将这些数量直接视作 2,925 个登记的互斥分解。</p><pre>'+html.escape(json.dumps(dict(retest_invalidations=dict(invalidations),entry_audit_outcomes=dict(outcomes)),ensure_ascii=False,indent=2))+'</pre>'
    extra+='<h2>成交记录</h2><table><tr><th>股票</th><th>买入日</th><th>买入价</th><th>信号日</th><th>净盈亏比</th></tr>'
    for a in filled:
        extra+='<tr>'+''.join('<td>'+html.escape(a[k])+'</td>' for k in ('symbol','date','fill','signal_date','net_rr'))+'</tr>'
    extra+='</table><p><a href="trades.csv">平仓交易</a> · <a href="orders.csv">全部订单</a> · <a href="equity.csv">每日净值</a></p>'
    report=OUT/'report.html';report.write_text(report.read_text(encoding='utf-8').replace('</body>', '').replace('</html>',extra+'</html>'),encoding='utf-8')
    shutil.copy2(__file__,OUT/'source')
    print(json.dumps(dict(summary=summary,verification=verification),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
