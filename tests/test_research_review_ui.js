// Offline DOM/canvas interaction checks; no claim of native download success.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const page=fs.readFileSync(process.argv[2],'utf8'),code=page.match(/<script>([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(code.match(/const cases=([\s\S]*?),run=/)[1]);
const nodes=new Map(),store=new Map();let count=0,drawings=0,payload=null,downloaded=false;
function node(id){if(nodes.has(id))return nodes.get(id);const ctx={scale(){},beginPath(){},moveTo(...a){assert(a.every(Number.isFinite))},lineTo(...a){assert(a.every(Number.isFinite))},stroke(){drawings++},fillRect(...a){assert(a.every(Number.isFinite))},fillText(){},setLineDash(){}};
 const n={id,value:'',checked:false,textContent:'',clientWidth:1000,children:[],handlers:{},append(...xs){this.children.push(...xs)},replaceChildren(){this.children=[]},addEventListener(k,f){this.handlers[k]=f},getContext(){return ctx},getBoundingClientRect(){return {left:0}},click(){downloaded=true},remove(){}};
 Object.defineProperty(n,'id',{get(){return id},set(v){id=v;nodes.set(v,n)}});nodes.set(id,n);return n;}
const document={getElementById:node,createElement:()=>node('created'+(++count)),body:node('body')};
const sandbox={document,devicePixelRatio:1,localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 window:{addEventListener(){}},setTimeout:f=>f(),Blob,URL:{createObjectURL:b=>{payload=b;return 'blob:test'},revokeObjectURL(){}}};
vm.runInNewContext(code,sandbox);
assert(data.length>0);let actions=0;
for(const c of data){
 assert(node('title').textContent.includes(c.case_id));
 for(const p of c.panels){assert(p.bars.every(b=>b.date<=c.as_of));}
 assert(!('symbol' in c));assert(!('pnl' in c));assert(!('outcomes' in c));
 node('annotations').checked=true;node('annotations').onchange();
 for(const canvas of node('charts').children){canvas.onmousemove({clientX:350});assert(/开/.test(node('tip').textContent));canvas.onmouseleave();}
 for(const field of ['structure','ownership','timing']){node(field).value='unclear';node(field).onchange();}
 node('next').onclick();assert.equal(node('annotations').checked,false);actions+=6;
}
node('reviewer').value='UI test';node('reviewer').handlers.input();node('export').onclick();
assert(downloaded);assert(payload);
payload.text().then(text=>{const p=JSON.parse(text);assert.equal(Object.keys(p.labels).length,data.length);assert.equal(p.reviewer,'UI test');assert.equal(p.independent,false);console.log(JSON.stringify({passed:true,cases:data.length,actions,canvas_strokes:drawings,export_payload_checked:true,native_download_verified:false}));}).catch(e=>{console.error(e);process.exitCode=1});
