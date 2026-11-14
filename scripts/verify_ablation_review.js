/* DOM/canvas logic check only; this does not assert native browser downloads. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const file=process.argv[2],source=fs.readFileSync(file,'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const storage=new Map(),downloads=[],blobs=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.clientWidth=1200;this.value='';this.textContent=''}
  append(...children){this.children.push(...children)}
  replaceChildren(...children){this.children=children}
  addEventListener(name,fn){this.listeners[name]=fn}
  getContext(){return new Proxy({},{get:()=>()=>{},set:()=>true})}
  getBoundingClientRect(){return {left:0}}
  click(){downloads.push({href:this.href,name:this.download})}
  remove(){}
}
const elements=new Map();
function collect(e,id){if(e.id===id)return e;for(const c of e.children){let f=collect(c,id);if(f)return f}}
const document={body:new Element('body'),createElement:t=>new Element(t),getElementById:id=>{
  for(const e of elements.values()){let got=collect(e,id);if(got)return got}
  if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id)
}};
const context=vm.createContext({document,devicePixelRatio:1,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
  window:{addEventListener:()=>{}},Blob,URL:{createObjectURL:b=>{blobs.push(b);return 'blob:verified'},revokeObjectURL:()=>{}},
  setTimeout:()=>{},Date,console});
vm.runInContext(source,context);
const cases=vm.runInContext('cases',context);
assert(cases.length>0);let actions=0;
for(let i=0;i<cases.length;i++){
  const c=cases[i];assert(document.getElementById('title').textContent.includes(c.case_id));
  assert(!('variant' in c));assert(!('net_pnl' in c));assert(!('category' in c));
  const charts=document.getElementById('charts').children;assert.equal(charts.length,3);
  c.panels.forEach((p,j)=>{
    assert(p.bars.every(b=>b.date<=c.as_of));
    charts[j].children[0].listeners.mousemove({clientX:400});
    assert(/\d{8} 开/.test(charts[j].children[1].textContent));actions++;
  });
  for(const k of ['core','rhythm','timing']){document.getElementById(k).value='unclear';document.getElementById(k).listeners.change();actions++}
  document.getElementById('next').onclick();actions++;
}
document.getElementById('export').onclick();actions++;
assert(downloads[0].name.endsWith('-labels.json'));assert.equal(downloads[0].href,'blob:verified');
blobs[0].text().then(text=>{
  const p=JSON.parse(text);assert.equal(p.schema,'rule-ablation-review-v1');assert.equal(Object.keys(p.labels).length,cases.length);
  assert(Object.values(p.labels).every(v=>v.core==='unclear'&&v.rhythm==='unclear'&&v.timing==='unclear'));
  console.log(JSON.stringify({passed:true,cases:cases.length,actions,native_browser_verified:false,
    checks:['causal candles','hidden groups/outcomes','crosshair date','navigation','draft persistence','download JSON payload']}));
});
