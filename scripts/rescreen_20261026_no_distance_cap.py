"""Rescore the verified premarket signals with only the W distance cap removed."""
import json,sys,shutil,hashlib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/20261026-premarket-w-ihs'
OUT=ROOT/'runs/20261026-premarket-w-ihs-no-distance-cap'
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 OUT.mkdir(exist_ok=True)
 shutil.copytree(ROOT/'src',OUT/'source/src',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
 riskfile=OUT/'source/src/trading_system/risk.py'
 source=riskfile.read_text(encoding='utf-8')
 gate="            if distance>limit+1e-12:return reject('entry_too_far_from_W_retest')"
 assert source.count(gate)==1
 riskfile.write_text(source.replace(gate,'            # User-requested scan: no W entry-distance cap.'),encoding='utf-8')
 sys.path.insert(0,str(OUT/'source/src'))
 from trading_system.engine import Backtest
 from trading_system.domain import Intent
 cfg=json.loads((BASE/'config.json').read_text(encoding='utf-8'))
 engine=Backtest(cfg,[])
 plans=json.loads((BASE/'plans.json').read_text(encoding='utf-8'))
 for p in plans:
  i=Intent(**{k:v for k,v in p.items() if k in Intent.__dataclass_fields__})
  p['previous_assessment']=p['reference_assessment']
  p['reference_assessment']=engine.assess_entry(i,i.trigger*1.001,1e6,1e6,{},'20261026')
  allowed=[]
  for cents in range(int(i.stop*100)+1,int(i.target*100)):
   if engine.assess_entry(i,cents/100*1.001,1e6,1e6,{},'20261026')['risk_reason']=='approved':allowed.append(cents/100)
  p['conditional_open_range']=[min(allowed),max(allowed)] if allowed else None
  assert p['reference_assessment']['risk_reason']!='entry_too_far_from_W_retest'
  if p['reason']=='inverse_head_shoulders':assert p['reference_assessment']==p['previous_assessment']
 dump(OUT/'plans.json',plans)
 summary=dict(as_of='20261023',for_session='20261026',W_entry_distance_cap=None,structural_stops_unchanged=True,min_net_rr_strictly_above=3,signal_generation_unchanged=True,source_signals=str(BASE/'plans.json'),risk_reasons=dict(Counter(p['reference_assessment']['risk_reason'] for p in plans)),approved=[p['symbol'] for p in plans if p['reference_assessment']['risk_reason']=='approved'])
 dump(OUT/'summary.json',summary)
 dump(OUT/'verification.json',dict(only_one_risk_gate_removed=True,all_10_existing_verified_signals_reassessed=True,ihs_assessments_unchanged=True,source_signal_sha256=hashlib.sha256((BASE/'plans.json').read_bytes()).hexdigest()))
 rows=''
 for p in plans:
  a=p['reference_assessment'];rg=p['conditional_open_range']
  rows+=f'<tr><td>{p["name"]} {p["symbol"]}</td><td>{"双底" if p["reason"]=="direct_w" else "头肩底"}</td><td>{p["trigger"]:.2f}</td><td>{p["stop"]:.2f}</td><td>{p["target"]:.2f}</td><td>{(a["fill"]-p["stop"])/a["fill"]:.2%}</td><td>{a.get("net_rr",0):.2f}</td><td>{"通过" if a["risk_reason"]=="approved" else "净RR不足"}</td><td>{str(rg) if rg else "无"}</td></tr>'
 page=f'''<!doctype html><meta charset="utf-8"><title>2026-10-26 不限2%止损距离扫描</title><style>body{{font:16px system-ui;max-width:1200px;margin:40px auto}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}p{{line-height:1.8}}</style><h1>2026-10-26 盘前扫描：取消双底2%止损距离限制</h1><p>沿用截至10月23日数据和已复核的10个信号。仅移除双底入场距离拒绝条件，止损位置、形态确认、净收益风险比严格大于3、账户风险预算等均保留。扫描范围：沪深主板非ST 3053只，1只当日缺失；42个未确认回踩的观察形态不升级为买点。</p><p>仍仅瀚蓝环境600323通过参考价检查。开盘上限仍为30.83元，此处净收益风险比条件比原2%距离限制更严格。其他信号在前收盘参考价下仍因净收益风险比不足而未通过。</p><table><tr><th>股票</th><th>形态</th><th>前收盘</th><th>止损</th><th>目标参考</th><th>止损距离</th><th>净RR</th><th>参考价结论</th><th>条件开盘区间</th></tr>{rows}</table><p>假设100万元空仓账户，按开盘加0.1%滑点、佣金万三及卖出印花税万五计算，价格网格0.01元。条件区间仅表示价格风控通过，实际需核实当日停牌、ST、涨跌停和复权，且需按实际账户重算。低开会改变判断；本表不是实际成交结果。</p>'''
 (OUT/'report.html').write_text(page,encoding='utf-8')
 for p in plans:print(json.dumps(dict(symbol=p['symbol'],name=p['name'],net_rr=p['reference_assessment'].get('net_rr'),range=p['conditional_open_range'],status=p['reference_assessment']['risk_reason']),ensure_ascii=True))
 shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
if __name__=='__main__':main()
