/* Browser storage state only; no reviewer switch may discard a working draft. */
(function(root){
class ReviewDraft {
 constructor(storage,pack,ids){this.storage=storage;this.pack=pack;this.ids=new Set(ids);this.labels={};this.reviewer='';this.storageError=false;this.restoredFrom='';}
 valid(labels){const out={};for(const [id,value] of Object.entries(labels||{})){if(this.ids.has(id)&&value&&typeof value==='object'){out[id]={id,double_bottom:value.double_bottom||'',retest:value.retest||'',confirmed_date:value.confirmed_date||'',notes:value.notes||''};}}return out;}
 count(labels=this.labels){return Object.values(labels).filter(v=>v.double_bottom||v.retest||v.confirmed_date||v.notes).length;}
 read(key){try{return JSON.parse(this.storage.getItem(key)||'null');}catch(e){return null;}}
 candidates(){const result=[];try{for(let i=0;i<this.storage.length;i++){const key=this.storage.key(i);if(!key.startsWith(this.pack+':')||key.includes(':guides:'))continue;const raw=this.read(key);if(!raw||Array.isArray(raw))continue;const labels=this.valid(raw.labels||raw);const count=this.count(labels);if(count)result.push({key,labels,count,reviewer:raw.reviewer!==undefined?raw.reviewer:key.slice((this.pack+':').length),updated_at:raw.updated_at||''});}}catch(e){this.storageError=true;}return result.sort((a,b)=>b.count-a.count||b.updated_at.localeCompare(a.updated_at));}
 load(){const latest=this.read(this.pack+':draft-v2');if(latest&&this.count(this.valid(latest.labels))){this.labels=this.valid(latest.labels);this.reviewer=latest.reviewer||'';this.restoredFrom='latest';return;}const found=this.candidates();if(found.length){this.labels=found[0].labels;this.reviewer=found[0].reviewer==='draft-v2'?'':found[0].reviewer;this.restoredFrom=found[0].key;this.save();}}
 save(){try{this.storage.setItem(this.pack+':draft-v2',JSON.stringify({reviewer:this.reviewer,labels:this.labels,updated_at:new Date().toISOString()}));this.storageError=false;}catch(e){this.storageError=true;}}
 rename(name){this.reviewer=name.trim();this.save();}
 set(id,field,value){if(!this.ids.has(id))throw Error('Unknown case');if(!['double_bottom','retest','confirmed_date','notes'].includes(field))return;this.labels[id]||={id};this.labels[id][field]=value;this.save();}
 collect(values){this.labels=this.valid(values);this.save();}
 restore(candidate){if(this.count()){try{this.storage.setItem(this.pack+':backup-'+Date.now(),JSON.stringify({reviewer:this.reviewer,labels:this.labels,updated_at:new Date().toISOString()}));}catch(e){this.storageError=true;}}this.labels=this.valid(candidate.labels);this.reviewer=candidate.reviewer||this.reviewer;this.restoredFrom=candidate.key;this.save();}
 payload(mode){if(!this.reviewer)throw Error('请填写审核者名称，已有标注会保留。');const labels=Object.values(this.labels).filter(v=>v.double_bottom||v.retest||v.confirmed_date||v.notes);if(!labels.length)throw Error('没有可导出的标注。请使用“恢复历史草稿”查找之前填写的内容。');return {pack_id:this.pack,reviewer:this.reviewer,view_mode:mode,exported_count:labels.length,labels};}
}
function candleAt(point,panels){for(const panel of panels||[]){const b=panel.bounds;if(point.x<b.left||point.x>b.right||point.y<b.top||point.y>b.bottom)continue;const x=panel.xlim[0]+(point.x-b.left)/(b.right-b.left)*(panel.xlim[1]-panel.xlim[0]);const index=Math.max(0,Math.min(panel.bars.length-1,Math.round(x)));const candle=panel.bars[index];return {panel:panel.kind,candle,index,x:b.left+(index-panel.xlim[0])/(panel.xlim[1]-panel.xlim[0])*(b.right-b.left),bounds:b,cursorPrice:panel.ylim[1]-(point.y-b.top)/(b.bottom-b.top)*(panel.ylim[1]-panel.ylim[0])};}return null;}
root.ReviewDraft=ReviewDraft;root.candleAt=candleAt;
if(typeof module!=='undefined')module.exports={ReviewDraft,candleAt};
})(typeof window==='undefined'?globalThis:window);
