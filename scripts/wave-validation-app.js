'use strict';
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const reasons={qualified:'符合当前规则',geometry:'几何关系不合格',duration_below_three:'调整少于3根日线',correction_longer_than_impulse:'调整长于上涨段',correction_too_fast:'调整速率过快',correction_span_too_large:'调整幅度过大',floor_broken:'核心低点已失守',projection_consumed:'投射空间已经到达',latest_core_not_qualified:'最新调整不合格，v5.10拒绝旧核心',no_core_n:'无合格核心'};
Object.assign(reasons,{wave_waiting:'等待新的合格核心',wave_recovering:'等待确认低点后的恢复',wave_unresolved:'时间与幅度级别不一致，暂停入场',wave_child_failed_waiting_for_new_floor:'子低点失守，等待新的确认低点',adjustment_timeout:'调整超时',order_unknown:'同根K线高低点顺序不明',replaced_by_core:'被合格本级后继接替'});
const waveStates={active:'父核心尚未结束',ended:'已结束，禁止复用',observed:'内部子结构已确认',failed:'子结构低点已失守',parent_ended:'父核心已结束'};
const waveRelations={independent:'独立核心',internal:'内部子结构',same_level_successor:'本级后继'};
function table(headers,rows){return '<table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
function current(){return DATA.cases[Number($('case').value)];}
function frame(){return current().frames[Number($('time').value)];}
for(let i=0;i<DATA.cases.length;i++){const c=DATA.cases[i],o=document.createElement('option');o.value=i;o.textContent=c.id+' · '+c.symbol+' · '+c.as_of+(c.note?' · '+c.note:'');$('case').append(o);}
const charts={};
function draw(scale){
 const canvas=$(scale),ctx=canvas.getContext('2d'),f=frame(),bars=f.candles[scale],w=canvas.width,h=canvas.height;
 ctx.clearRect(0,0,w,h);if(!bars.length)return;
 const left=60,right=18,top=20,bottom=38,step=(w-left-right)/bars.length;
 const lo=Math.min(...bars.map(b=>b.low)),hi=Math.max(...bars.map(b=>b.high)),padding=(hi-lo)*.04||1;
 const ymin=lo-padding,ymax=hi+padding,y=v=>top+(ymax-v)/(ymax-ymin)*(h-top-bottom);
 const dates=new Map(bars.map((b,i)=>[b.date,i])),x=i=>left+(i+.5)*step;
 for(let k=0;k<=5;k++){const price=ymin+(ymax-ymin)*k/5;ctx.strokeStyle='#e6eaf0';ctx.beginPath();ctx.moveTo(left,y(price));ctx.lineTo(w-right,y(price));ctx.stroke();ctx.fillStyle='#526277';ctx.fillText(price.toFixed(2),5,y(price));}
 bars.forEach((b,i)=>{ctx.strokeStyle=ctx.fillStyle=b.close>=b.open?'#c75454':'#45927c';ctx.beginPath();ctx.moveTo(x(i),y(b.high));ctx.lineTo(x(i),y(b.low));ctx.stroke();ctx.fillRect(x(i)-Math.max(1,step*.3),Math.min(y(b.open),y(b.close)),Math.max(1,step*.6),Math.max(1,Math.abs(y(b.open)-y(b.close))));});
 for(let i=0;i<bars.length;i+=Math.max(1,Math.floor(bars.length/8))){ctx.fillStyle='#526277';ctx.fillText(bars[i].date,x(i)-25,h-12);}
 function poly(nodes,color,dashed=false){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dashed?[5,4]:[]);ctx.beginPath();let started=false;for(const n of nodes){const i=dates.get(scale==='weekly'?n.bar_date:n.date);if(i===undefined){started=false;continue;}if(started)ctx.lineTo(x(i),y(n.price));else ctx.moveTo(x(i),y(n.price));started=true;}ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;}
 poly(f.nodes[scale],scale==='weekly'?'#c12638':'#d98816');
 if(scale==='daily'){
  poly(f.nodes.daily_nested_proxy,'#367fba',true);
  const models=[['legacy','#1e8b50'],['latest','#8a41a1']];if(f.nested)models.push(['nested','#252dc2']);
  for(const [mode,color] of models){const core=f[mode].core;if(!core)continue;const candidate=mode==='nested'?core:f.candidates.find(c=>c.a===core.a&&c.b===core.b&&c.c===core.c);if(!candidate)continue;
   poly(['a','b','c'].map(k=>({date:candidate[k],price:candidate[k+'_price']})),color);
   for(const key of ['floor','target']){if(core[key]<ymin||core[key]>ymax)continue;ctx.setLineDash([7,4]);ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(left,y(core[key]));ctx.lineTo(w-right,y(core[key]));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=color;ctx.fillText(mode+' '+(key==='floor'?'失效低点':'投射目标')+' '+core[key].toFixed(3),w-250,y(core[key])-4);}
  }
 }
 charts[scale]={bars,step,left,x,y,base:ctx.getImageData(0,0,w,h)};
}
function render(){
 const c=current(),f=frame();$('date').textContent=' 当前时点 '+f.as_of+(f.as_of>c.focus_date?'（后续观察）':'');
 const r=c.reference;$('reference').textContent=r?'原审核：双底 '+r.double_bottom+'；回踩 '+r.retest+'；备注 '+(r.notes||'无'):'该案例没有原波段边界审核标签';
 draw('weekly');draw('daily');
 const modes=['legacy','latest'];if(f.nested)modes.push('nested');
 $('state').innerHTML='<h3>当时的核心判断</h3>'+table(['算法','核心A/B/C','确认日期','判断','小结构归属'],modes.map(k=>{const a=f[k],core=a.core;return [k==='legacy'?'v5.9.1旧核心选择':k==='latest'?'v5.10最新调整选择':'v5.11波段状态机',core?[core.a,core.b,core.c].join(' / '):'无',core?.confirmed||'无',reasons[a.reason]||a.reason,k==='nested'?(a.rhythm_owner||'未确定'):a.small?'恢复窗口内候选；父子级别尚未证实':a.small_reason||'无'];}))+
 '<p>后续调整中同时更短、更小的候选：'+f.later_corrections.filter(a=>a.smaller_in_both).length+' 个。这只是尺度线索，不能据此自动认可旧核心或升级新核心。</p>';
 $('candidates').innerHTML=table(['A','B','C','首次可确认','调整日数','调整幅度','失效低点','投射目标','当时状态'],f.candidates.slice(-12).map(c=>[c.a,c.b,c.c,c.confirmed,c.duration,c.range.toFixed(3),c.floor.toFixed(3),c.target.toFixed(3),reasons[c.reason]||c.reason]));
 const nodes=[...f.nodes.weekly,...f.nodes.daily,...f.nodes.daily_nested_proxy];
 const recentRelations=[...f.relations.filter(r=>r.child.startsWith('daily:')).slice(-10),...f.relations.filter(r=>r.child.startsWith('daily_nested_proxy:')).slice(-10)];
 $('relations').innerHTML='<p>关系仅由起止日期包含生成。跨界和末端未完成的结构保留未归属，不补造父级。</p>'+table(['子波段','时间包含的上级波段','结论'],recentRelations.map(r=>[r.child,r.parent||'未归属',r.parent?'时间包含；交易层级未验证':'跨界或父级尚未完成']));
 $('relations').innerHTML+='<details><summary>枢轴发生日期与确认日期（最近24个）</summary>'+table(['层级','类型','发生日期','K线日期','确认日期','价格'],nodes.slice(-24).map(n=>[n.scale,n.kind,n.date,n.bar_date,n.confirmed,n.price.toFixed(3)]))+'</details>';
 if(f.nested){const ledger=Object.values(f.nested.ledger);$('relations').innerHTML+='<h3>v5.11规则定义的归属与生命周期（待独立验证）</h3><p>父核心尚未结束时，也可能因子结构失败或级别未确定而暂停入场。是否可评估新计划，以“当时的核心判断”为准。</p>'+table(['波段A/B/C','父波段','关系','接受时间','当前状态','结束或失败原因'],ledger.slice(-16).map(r=>[[r.a,r.b,r.c].join(' / '),r.parent_owner||'独立核心',waveRelations[r.relation]||r.relation,r.accepted_at,waveStates[r.state]||r.state,reasons[r.end_reason]||r.end_reason||r.failed_at||'']));}
 $('summary').textContent=JSON.stringify(DATA.summary,null,2);
}
let loadToken=0;
async function select(){const token=++loadToken,c=current();
 if(!c.frames){$('date').textContent='正在加载案例…';
  try{const bytes=Uint8Array.from(atob(c.frames_gzip),v=>v.charCodeAt(0));
   const decoded=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
   if(token!==loadToken)return;
   for(const other of DATA.cases)if(other!==c)delete other.frames;
   c.frames=JSON.parse(decoded);
  }catch(error){$('date').textContent='案例加载失败：'+error.message;return;}
 }
 if(token!==loadToken)return;
 $('time').min=0;$('time').max=c.frames.length-1;$('time').value=c.frames.findIndex(f=>f.as_of===c.focus_date);render();}
$('case').addEventListener('change',select);$('time').addEventListener('input',render);
for(const [id,delta] of [['prev',-1],['next',1]])$(id).addEventListener('click',()=>{$('time').value=Math.min(Number($('time').max),Math.max(0,Number($('time').value)+delta));render();});
$('focus').addEventListener('click',select);
for(const scale of ['weekly','daily']){
 $(scale).addEventListener('mousemove',event=>{const canvas=$(scale),chart=charts[scale];if(!chart)return;const rect=canvas.getBoundingClientRect(),px=(event.clientX-rect.left)*canvas.width/rect.width,py=(event.clientY-rect.top)*canvas.height/rect.height;
  const i=Math.floor((px-chart.left)/chart.step);if(i<0||i>=chart.bars.length)return;
  const ctx=canvas.getContext('2d');ctx.putImageData(chart.base,0,0);ctx.strokeStyle='#222';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(chart.x(i),0);ctx.lineTo(chart.x(i),canvas.height);ctx.moveTo(0,py);ctx.lineTo(canvas.width,py);ctx.stroke();ctx.setLineDash([]);
  const b=chart.bars[i],label=b.date;ctx.fillStyle='#222';ctx.fillRect(chart.x(i)-36,canvas.height-24,76,24);ctx.fillStyle='white';ctx.fillText(label,chart.x(i)-31,canvas.height-8);
  $('hover').textContent=(scale==='weekly'?'周线结束日 ':'日线 ')+b.date+' 开 '+b.open.toFixed(3)+' 高 '+b.high.toFixed(3)+' 低 '+b.low.toFixed(3)+' 收 '+b.close.toFixed(3);
 });
 $(scale).addEventListener('mouseleave',()=>{const c=charts[scale];if(c)$(scale).getContext('2d').putImageData(c.base,0,0);});
}
const requestedCase=new URLSearchParams(location.search).get('case');
if(requestedCase){const index=DATA.cases.findIndex(c=>c.id===requestedCase);if(index>=0)$('case').value=String(index);}
select();
