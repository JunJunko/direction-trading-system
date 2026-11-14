// Offline interaction checks; canvas calls are checked, not pixel screenshots.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const page=fs.readFileSync(process.argv[2],'utf8');
const DATA=JSON.parse(page.match(/<script>const DATA=([\s\S]*?);<\/script>/)[1]);
const nodes=new Map();let drawings=0;
function node(id){if(nodes.has(id))return nodes.get(id);const handlers={};
 const ctx={clearRect(){},beginPath(){},moveTo(...v){assert(v.every(Number.isFinite));},lineTo(...v){assert(v.every(Number.isFinite));},stroke(){drawings++;},fillRect(...v){assert(v.every(Number.isFinite));},fillText(){},setLineDash(){},getImageData(){return {};},putImageData(){}};
 const element={value:'0',min:'0',max:'0',width:1400,height:350,textContent:'',innerHTML:'',
  append(){},addEventListener(k,f){handlers[k]=f;},handlers,getContext(){return ctx;},getBoundingClientRect(){return {left:0,top:0,width:700,height:175};}};
 nodes.set(id,element);return element;
}
const document={getElementById:node,createElement:()=>({})};
const code=fs.readFileSync('scripts/wave-validation-app.js','utf8');
(async()=>{
 const context={DATA,document,Blob,Response,DecompressionStream,atob,Uint8Array,URLSearchParams,location:{search:''}};
 await vm.runInNewContext(code,context);
 let actions=0;
 for(let i=0;i<DATA.cases.length;i++){
  node('case').value=String(i);await node('case').handlers.change();
  const c=DATA.cases[i];assert(node('date').textContent.includes(c.focus_date));
  const initial=Number(node('time').value);
  node('prev').handlers.click();assert.equal(Number(node('time').value),Math.max(0,initial-1));
  node('next').handlers.click();assert.equal(Number(node('time').value),initial);
  await node('focus').handlers.click();
  for(const scale of ['daily','weekly']){
   node(scale).handlers.mousemove({clientX:300,clientY:80});
   assert(/\d{8}.*开/.test(node('hover').textContent));
   node(scale).handlers.mouseleave();actions++;
  }
  assert(node('relations').innerHTML.includes('交易层级未验证'));
  assert(node('candidates').innerHTML.includes('失效低点'));
  assert.equal(DATA.cases.filter(c=>c.frames).length,1);
  actions+=4;
 }
 console.log(JSON.stringify({cases:DATA.cases.length,actions,canvas_strokes:drawings,passed:true,scope:'DOM and canvas-command checks; not browser screenshots'}));
})().catch(e=>{console.error(e);process.exitCode=1;});
