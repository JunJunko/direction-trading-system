"""Entry-only audit. No counterfactual exits or changed trading rules."""
import csv,json,hashlib,statistics,html
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];O=ROOT/'audits/20261025-entry-risk-definition';O.mkdir(exist_ok=True)
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def save(p,rs):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def table(h,rs):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in rs)+'</table></div>'
def f(v):return '—' if v is None else f'{v:.3f}'
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')}
allrows=[];summaries=[];planrows=[]
for cohort,market,base in [('IHS',ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest',ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'),('W',ROOT/'runs/20261024-qualified-w-cohort',ROOT/'runs/20261024-qualified-w-cohort/candidate')]:
 plans=load(market/'plans.json');pm={p['setup_id']:p for p in plans};fills=[r for r in rows(base/'entry_audit.csv') if r.get('execution_reason')=='filled'];needed={r['symbol'] for r in fills};by=defaultdict(list);cfg=load(base/'config.json')
 with (market/'bars.csv').open(encoding='utf-8-sig',newline='') as file:
  for r in csv.DictReader(file):
   if r['symbol'] in needed and r['date']<='20260930':by[r['symbol']].append(r)
 prefix='ihs' if cohort=='IHS' else 'w'
 for p in plans:
  entry=float(p['trigger']);stop=float(p['stop']);target=float(p['target']);local=float(p[prefix+'_retest_low']);neck=float(p[prefix+'_neckline'])
  planrows.append(dict(cohort=cohort,symbol=p['symbol'],signal_date=p['date'],setup_id=p['setup_id'],signal_reference=entry,stop=stop,local_retest_low=local,neckline=neck,target=target,planned_stop_distance_pct=(entry-stop)/entry*100,planned_target_distance_pct=(target-entry)/entry*100,planned_local_distance_pct=(entry-local)/entry*100,reference_only=True))
 for a in fills:
  p=pm[a['setup_id']];bs=sorted(by[a['symbol']],key=lambda r:r['date']);idx=next(i for i,b in enumerate(bs) if b['date']==a['date']);factor=float(bs[idx]['factor']);scale=float(p['factor'])/factor;entry=float(a['fill']);stop=float(a['stop']);target=float(a['target']);local=float(p[prefix+'_retest_low'])*scale;neck=float(p[prefix+'_neckline'])*scale;head=float(p[prefix+'_floor'])*scale
  def price(j,k):return float(bs[j][k])*float(bs[j]['factor'])/factor
  atr=statistics.mean(max(price(j,'high')-price(j,'low'),abs(price(j,'high')-price(j-1,'close')),abs(price(j,'low')-price(j-1,'close'))) for j in range(idx-14,idx))
  q=float(a['filled_quantity']);risk=float(a['expected_loss']);comm=cfg['execution']['commission_rate'];tax=cfg['execution']['sell_tax_after_20230828'];slip=cfg['execution']['slippage'];entryfee=max(5,q*entry*comm)
  def gain(t):
   value=q*t*(1-slip);return value-q*entry-entryfee-max(5,value*comm)-value*tax
  lo=entry;hi=target*2
  for _ in range(70):
   mid=(lo+hi)/2
   if gain(mid)>3*risk:hi=mid
   else:lo=mid
  assert abs(gain(target)/risk-float(a['net_rr']))<1e-8
  r=dict(cohort=cohort,symbol=a['symbol'],entry_date=a['date'],signal_date=p['date'],setup_id=a['setup_id'],entry=entry,stop=stop,stop_source='right_shoulder' if cohort=='IHS' else 'retest_low',local_retest_low=local,neckline=neck,head=head,target=target,stop_distance_pct=(entry-stop)/entry*100,local_distance_pct=(entry-local)/entry*100,stop_ATR=(entry-stop)/atr,local_ATR=(entry-local)/atr,target_distance_pct=(target-entry)/entry*100,target_ATR=(target-entry)/atr,minimum_target_for_net3R=hi,net_rr=float(a['net_rr']),quantity=q,expected_loss=risk,risk_budget=float(a['risk_budget']),budget_use_pct=risk/float(a['risk_budget'])*100,notional=q*entry,retest_date=p[prefix+'_retest_date'] if cohort=='IHS' else p['w_retest_low_date'],large_structure_first_date=p['ihs_left_date'] if cohort=='IHS' else p['w_left_date'],ATR14_known_before_entry=atr)
  allrows.append(r)
 rs=[r for r in allrows if r['cohort']==cohort];pr=[r for r in planrows if r['cohort']==cohort]
 summaries.append(dict(cohort=cohort,signals=len(plans),fills=len(rs),stop_distance_min=min(r['stop_distance_pct'] for r in rs),stop_distance_median=statistics.median(r['stop_distance_pct'] for r in rs),stop_distance_max=max(r['stop_distance_pct'] for r in rs),actual_over2pct=sum(r['stop_distance_pct']>2+1e-8 for r in rs),planned_over2pct=sum(r['planned_stop_distance_pct']>2+1e-8 for r in pr),median_local_distance=statistics.median(r['local_distance_pct'] for r in rs),target_distance_median=statistics.median(r['target_distance_pct'] for r in rs)))
save(O/'filled-entry-risk.csv',allrows);save(O/'all-signal-risk.csv',planrows);(O/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
body=['<h1>入场风险定义专项审计</h1><p>只检查入场时可知信息及审批逻辑，不读取未来收益来评价止损，不修改入场、止损、止盈或仓位规则。</p><h2>结论</h2><p><b>头肩底与双底当前并未使用同一种低风险入场定义。</b>头肩底 v3 用颈线回踩确认入场，却把初始止损设为右肩低点；其2%限制是“买入价距颈线”，不是“买入价距止损”。风险模块没有对应 ihs_retest 的初始价格风险上限及回踩低点止损一致性校验。</p><p>双底 v5.19 则把回踩低点作为初始止损，风险模块校验该止损与回踩低点一致、确认日期有效，并限制实际买入价到止损不超过2%。该2%是既有双底规则，本审计仅拿来对照，不把它自动移植为头肩底新规则。</p><p>两者都有账户预算与净收益风险比审核：按含成本止损损失确定数量，且目标净收益/预计止损损失必须严格大于3。但头肩底可以通过缩小仓位容纳较宽止损；远端形态目标又可满足净收益风险比。账户损失预算合规，不能证明价格介入风险低，也不能证明目标可达。</p>']
body.append(table(['策略','信号数','成交数','止损幅度最小/中位/最大%','成交中超过2%','信号参考超过2%','目标涨幅中位%'],[[r['cohort'],r['signals'],r['fills'],' / '.join(f(r[k]) for k in ['stop_distance_min','stop_distance_median','stop_distance_max']),r['actual_over2pct'],r['planned_over2pct'],f(r['target_distance_median'])] for r in summaries]))
r=next(r for r in allrows if r['symbol']=='600063.SH')
body.append('<h2>600063.SH：2025-10-22</h2>'+table(['项目','核验结果'],[['模拟买入价',f(r['entry'])],['右肩初始止损',f(r['stop'])],['止损幅度 / 前置ATR',f(r['stop_distance_pct'])+'% / '+f(r['stop_ATR'])],['回踩低点 / 距离',f(r['local_retest_low'])+' / '+f(r['local_distance_pct'])+'%'],['原始形态目标 / 涨幅',f(r['target'])+' / '+f(r['target_distance_pct'])+'%'],['满足净3R所需目标边界',f(r['minimum_target_for_net3R'])],['原始净收益风险比',f(r['net_rr'])],['预计损失 / 风险预算',f(r['expected_loss'])+' / '+f(r['risk_budget'])],['大形态起点 / 回踩日期',r['large_structure_first_date']+' / '+r['retest_date']]]))
body.append('<p>这一笔以2023年的左肩、2024年的头部、2025年的右肩构建较长周期目标，却在2025年10月的局部回踩入场。目标=2×颈线−头部低点。净3R边界只是固定原仓位、费用和原止损下的数学边界，不是新目标建议。6.20仅是审计中的局部低点，尚未被本轮验证为可交易的止损；不能直接改用它来制造高盈亏比。</p><h2>全部成交入场定义</h2>')
body.append(table(['策略','股票','买入日','买价','初始止损','止损幅度%','止损/ATR','回踩低点','局部距离%','局部距离/ATR','目标涨幅%','净收益风险比','预计损失元'],[[r['cohort'],r['symbol'],r['entry_date']]+[f(r[k]) for k in ['entry','stop','stop_distance_pct','stop_ATR','local_retest_low','local_distance_pct','local_ATR','target_distance_pct','net_rr','expected_loss']] for r in allrows]))
body.append('<h2>审计发现及职责边界</h2><ol><li>初始风险定义不一致：头肩底的右肩是较大结构失效位置，回踩低点是局部入场依据；两者职责尚未分离。</li><li>风险上限缺口：距颈线2%并不约束距右肩止损的风险，也不能用账户仓位缩小来代替局部价格风险校验。</li><li>目标依赖：目前门槛检验的是形态测算价格下的收益风险比，没有审核目标达到概率，也没有按入场时已知近端压力或目标时间尺度检验空间。不能据此断言必然不可达，但不可称为已验证的3R机会。</li><li>不能机械收紧止损：局部低点距买价很小、相对ATR偏小时，可能处于正常噪声范围；本表提供距离和ATR供审查，不输出最佳止损或替代回测。</li><li>账户预算只是模拟预期损失：跳空、跌停、T+1和成交偏差仍可导致超过预算。此处仅解释现有机制，没有新增风控阈值。</li></ol><h2>后续需要先定义的入场契约</h2><p>若进入修改阶段，应先明确“本次回踩确认在什么条件下失效”，再评估该位置与成交价的距离是否可接受、是否处在正常波动噪声内；无法形成合理局部风险位置就不入场。独立检查可验证的获利空间，远端形态目标只作背景参考。具体距离上限、缓冲和压力定义尚未授权或验证，本轮不选值、不重跑优化。</p><p>头肩底全部708个信号和双底全部既有信号的参考距离也已导出；信号价不是实际成交价，不能把信号表的超过2%计数当作新规则会拒绝的实际交易数。使用的历史数据截至2026-09-30，未访问样本外数据。</p><h2>下载</h2><p><a href="filled-entry-risk.csv">逐笔成交风险审计</a> · <a href="all-signal-risk.csv">全部信号参考风险</a> · <a href="summary.json">汇总</a></p>')
(O/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>入场风险定义审计</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:36px auto;padding:0 24px;background:#f5f7fb;color:#19344d}.scroll{overflow:auto}table{border-collapse:collapse;background:white;font-size:13px;margin:20px 0}td,th{padding:9px;border:1px solid #d9e3ef;white-space:nowrap}th{background:#e4edf7}p,li{max-width:1200px}</style>'+''.join(body),encoding='utf-8')
assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')}
(O/'verification.json').write_text(json.dumps(dict(source_unchanged=True,net_RR_recomputed=len(allrows),no_future_outcomes_used=True,source_hashes=hashes),ensure_ascii=False,indent=2),encoding='utf-8')
(O/Path(__file__).name).write_text(Path(__file__).read_text(encoding='utf-8'),encoding='utf-8')
print(json.dumps(summaries,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False))
