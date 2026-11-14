"""Summarize frozen experiment, exact account attribution and candidate rejections."""
import csv,html,json,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from trading_system.data import save_csv
RUN=ROOT/'runs/20261109-candidate-policy-full'
LABELS={'baseline':'旧基准：面积优先／只提交首选','area_selected':'面积优先／只消费首选','balance_single':'时间平衡优先／只提交首选','area_fallback':'面积优先／保留同日备选','balance_fallback':'时间平衡优先／保留同日备选'}
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 comparison=rows(RUN/'comparison.csv');audit=rows(RUN/'chart-audit/trade-audit.csv');diagnostics={};fallback=[];changes=[]
 base={r['canonical']:r for r in audit if r['policy']=='baseline'}
 for policy in LABELS:
  folder=RUN/(policy+'_combined_cost1');plans=load(RUN/(policy+'-plans.json'));byid={p['setup_id']:p for p in plans};groups=defaultdict(list)
  for p in plans:groups[p['symbol'],p['date']].append(p)
  entry=rows(folder/'entry_audit.csv');bysetup=defaultdict(list)
  for a in entry:bysetup[a['setup_id']].append(a)
  fills=[a for a in entry if int(a.get('filled_quantity') or 0)>0]
  current={r['canonical']:r for r in audit if r['policy']==policy}
  new=current.keys()-base.keys();removed=base.keys()-current.keys();shared=base.keys()&current.keys()
  common_delta=sum(float(current[k]['pnl'])-float(base[k]['pnl']) for k in shared)
  new_pnl=sum(float(current[k]['pnl']) for k in new);removed_pnl=sum(float(base[k]['pnl']) for k in removed)
  account=load(folder/'summary.json')
  assert abs(sum(float(r['pnl']) for r in current.values())-(account['final_equity']-account['initial_cash']))<1e-6,policy
  diagnostics[policy]=dict(signal_rejections=dict(Counter(a.get('risk_reason') or a.get('execution_reason') for a in entry if a.get('execution_reason')=='plan_rejected')),
   execution_rejections=dict(Counter(a.get('execution_reason') for a in entry if a['date']!=a['signal_date'] and not int(a.get('filled_quantity') or 0))),
   realized_pnl=sum(float(r['pnl']) for r in current.values() if r['closed']=='True'),open_pnl=sum(float(r['pnl']) for r in current.values() if r['closed']!='True'),
   new_pnl=new_pnl,removed_baseline_pnl=removed_pnl,common_position_pnl_delta=common_delta,
   total_pnl_delta=new_pnl-removed_pnl+common_delta)
  for k in sorted(new|removed):
   r=current[k] if k in new else base[k]
   changes.append(dict(policy=policy,change='added' if k in new else 'removed',**{a:r[a] for a in ('canonical','symbol','signal','entry','pnl','closed','chart_id','time_balance','span','candidate_rank')}))
  for a in fills:
   p=byid.get(a['setup_id'])
   if not p or p.get('candidate_rank',1)==1:continue
   preceding=[q for q in groups[p['symbol'],p['date']] if q['candidate_rank']<p['candidate_rank']]
   rejected=[dict(rank=q['candidate_rank'],setup_id=q['setup_id'],checks=[dict(date=x['date'],risk_reason=x.get('risk_reason'),execution_reason=x.get('execution_reason'),filled=x.get('filled_quantity')) for x in bysetup[q['setup_id']]]) for q in preceding]
   fallback.append(dict(policy=policy,symbol=p['symbol'],signal=p['date'],setup_id=p['setup_id'],rank=p['candidate_rank'],preceding=rejected))
 dump(RUN/'diagnostics.json',diagnostics);dump(RUN/'fallback-fill-lineage.json',fallback);save_csv(RUN/'trade-changes.csv',changes)
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
 for p in ('baseline','balance_single','area_fallback','balance_fallback'):
  eq=rows(RUN/(p+'_combined_cost1')/'equity.csv');dates=[r['date'] for r in eq]
  axes[0].plot(range(len(eq)),[(float(r['equity'])/1000000-1)*100 for r in eq],label=p)
  axes[1].plot(range(len(eq)),[float(r['drawdown'])*100 for r in eq],label=p)
 axes[0].set_ylabel('Net return (%)');axes[1].set_ylabel('Drawdown (%)');axes[0].legend()
 ticks=list(range(0,len(dates),max(1,len(dates)//8)));axes[1].set_xticks(ticks,[dates[i] for i in ticks],rotation=20)
 for a in axes:a.grid(alpha=.2)
 fig.tight_layout();fig.savefig(RUN/'comparison.png',dpi=130);plt.close(fig)
 notes=load(RUN/'review-notes.json') if (RUN/'review-notes.json').exists() else {'headline':'全量候选规则对照','paragraphs':[],'examples':[]}
 page='<meta charset="utf-8"><title>候选选择与消费规则对照</title><style>body{max-width:1250px;margin:35px auto;font:16px/1.75 system-ui;color:#233044}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d8e0e7;padding:8px;text-align:right}td:first-child,th:first-child{text-align:left}img{max-width:100%}h1,h2{color:#183852}a{color:#136a8a}</style>'
 page+='<h1>'+html.escape(notes['headline'])+'</h1>'
 for p in notes['paragraphs']:page+='<p>'+html.escape(p)+'</p>'
 page+='<p>范围：3,214只沪深主板股票；2,856,672根日K；2023-01-03起预热；评估2025-10-09至2026-09-30。初始资金100万元，净盈亏比&gt;3、预期空间&gt;5%，同一风险预算与退出规则。组合为头肩底优先＋周线W v3。</p>'
 page+='<h2>全部20组账户结果</h2><table><tr><th>规则</th><th>账户</th><th>费用倍率</th><th>净收益</th><th>最大回撤</th><th>买入/平仓</th><th>胜率</th><th>获利因子</th><th>备选成交</th></tr>'
 for r in comparison:
  page+=f"<tr><td>{LABELS[r['policy']]}</td><td>{'组合' if r['combined']=='True' else '头肩底单独'}</td><td>{r['cost']}</td><td>{float(r['total_return']):+.2%}</td><td>{abs(float(r['max_drawdown'])):.2%}</td><td>{r['filled_buys']}/{r['closed_trades']}</td><td>{float(r['win_rate']):.2%}</td><td>{float(r['profit_factor']):.3f}</td><td>{r['fallback_fills']}</td></tr>"
 page+='</table><p>费用2倍指佣金率和买卖滑点翻倍，最低佣金及印花税口径不变。期末持仓按市值计入净收益，胜率和获利因子只含已平仓交易。</p><img src="comparison.png">'
 stats=load(RUN/'chart-audit/summary.json');page+='<h2>实际成交形态与损失诊断</h2><table><tr><th>规则</th><th>头肩底笔数</th><th>四段时间平衡中位数</th><th>跨度&gt;250日</th><th>最长段&gt;最短段10倍</th><th>外肩≤2日</th><th>亏损交易</th><th>亏损合计</th></tr>'
 for p,s in stats.items():page+=f"<tr><td>{LABELS[p]}</td><td>{s['IHS']}</td><td>{s['median_balance']:.4f}</td><td>{s['span_gt250']}</td><td>{s['leg_ratio_gt10']}</td><td>{s['outer_at_most2']}</td><td>{s['closed_losses']}</td><td>{s['loss_pnl']:,.0f}</td></tr>"
 page+='</table><p>这些几何指标只是可复查的诊断代理，不是经过人工标注验证的误判率。时间平衡是本次直接优化的指标，不能单凭该指标上升宣称形态识别改善。</p>'
 for e in notes['examples']:
  page+='<h2>'+html.escape(e['title'])+'</h2><p>'+html.escape(e['text'])+'</p>'
  for image in e.get('images',[]):page+='<img src="'+html.escape(image,quote=True)+'">'
 page+='<h2>核验与复现</h2><p>基准全部信号及成交账本逐项复现；候选排序只读取截至信号日的信息，同日备选在收盘和实际下一交易日开盘分别复核，同股至多一个持仓；错过的突破不延后重试。1,795只股票进行了逐日候选扫描；其余股票利用几何与首次突破条件不变这一性质，复用原全量扫描的全部1,713个信号日期，在完整历史前缀上重建竞争候选，并重新进行完整账户回放。不是只重放旧账户34笔成交。六只股票的等价性验证、独立普通策略回放与全局基准复现分别记录。详细结果见下列核验文件。</p>'
 for path,label in [('chart-audit/charts.html','逐笔结构图与持仓K线'),('comparison.csv','20组指标CSV'),('chart-audit/trade-audit.csv','逐笔几何/收益诊断CSV'),('trade-changes.csv','新增与移除交易'),('fallback-fill-lineage.json','每笔备选成交的拒绝链'),('scan-verification.json','全市场扫描一致性'),('verification.json','账户与风控核验'),('ordinary-verification/verification.json','独立普通策略回放'),('ordinary-tail-verification/verification.json','后段股票普通策略回放'),('chart-audit/verification.json','退出与保护线核验'),('protocol.json','事前冻结协议与代码指纹'),('execution-notes.json','计算加速与复核记录')]:page+=f'<p><a href="{path}">{label}</a></p>'
 page+='<p>限制：这是已被多次研究的开发样本，没有未使用的样本外数据，不能据此认定新规则具有稳定优势。K线图复核为非盲人工辅助审查；此前部分交易及收益已知。日线执行与复权沿用原研究近似。</p>'
 page+='<p><a href="matched-trade-attribution.json">同股同信号日的收益归因</a> · <a href="chart-audit/visual-review.json">45张结构图逐图观察</a> · <a href="tests.log">测试结果</a> · <a href="manifest.json">最终文件指纹</a></p>'
 page=page.replace('<th>外肩≤2日</th>','<th>至少一侧外肩≤2日</th>')
 (RUN/'report.html').write_text(page,encoding='utf-8');print(json.dumps(diagnostics,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
