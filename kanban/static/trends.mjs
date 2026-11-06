import {dailyDate, prefillSpeed, tpotP90, quantizationLabel} from './summary-model.mjs';
export const metrics = {
 decode: {label:'Decode 速度（P90）',unit:'token/s',higher:true,get:r=>r.timing?.decode_tps?.p90},
 prefill: {label:'Prefill 速度（P90 时延换算）',unit:'token/s',higher:true,get:prefillSpeed},
 ttft: {label:'TTFT P90',unit:'ms',get:r=>r.timing?.ttft_ms?.p90},
 tpot: {label:'TPOT P90',unit:'ms/token',get:tpotP90},
 ram: {label:'RAM · 稳定总 PSS 中位数',unit:'MiB',get:r=>r.memory?.total_pss_kib?.stable_median == null ? null : r.memory.total_pss_kib.stable_median/1024},
 rom: {label:'ROM',unit:'MiB',get:r=>r.model?.bytes == null ? null : r.model.bytes/1048576},
 init: {label:'模型初始化',unit:'ms',get:r=>r.initialization?.model_init_ms}
};
const canonical = x => x && typeof x==='object' ? Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])) : x;
export function seriesKey(r) {
 return JSON.stringify(canonical({recipe:r.recipe_id,framework:r.framework,backend:r.backend,spec:r.spec,device:r.device,quant:quantizationLabel(r)}));
}
export function trendGroups(runs) {
 const groups=new Map();
 for(const r of runs){const key=seriesKey(r);if(!groups.has(key)) groups.set(key,{key,run:r,label:`${r.spec?.model} / ${r.spec?.soc} / ${r.framework} / ${quantizationLabel(r)}`});}
 const result=[...groups.values()];
 const counts=new Map(); for(const g of result) counts.set(g.label,(counts.get(g.label)||0)+1);
 for(const g of result) if(counts.get(g.label)>1) g.label+=` · 配置 ${result.indexOf(g)+1}`;
 return result;
}
const shift = (day,n) => new Date(Date.parse(day+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
export function weekStart(day){const d=new Date(day+'T00:00:00Z');return shift(day,-((d.getUTCDay()+6)%7));}
export function trendPoints(runs,jobs,key,end,grain='day',windowDays=30,metric='decode') {
 if(!end || !metrics[metric]) return [];
 const start=shift(end,1-windowDays), byId=new Map(runs.map(r=>[r.id,r])), daily=new Map();
 // Only successful measurements, never reused results or historical fallback.
 for(const j of [...jobs].sort((a,b)=>Date.parse(a.started_at)-Date.parse(b.started_at))){
  const date=dailyDate(j),r=byId.get(j.result_id);
  if(j.status==='SUCCEEDED' && r && seriesKey(r)===key && date>=start && date<=end) daily.set(date,r);
 }
 const buckets=new Map();
 for(let day=start;day<=end;day=shift(day,1)){
  const period=grain==='week'?weekStart(day):day;
  if(!buckets.has(period)) buckets.set(period,{date:period,days:0,runs:[],values:[]});
  const b=buckets.get(period); b.days++;
  const r=daily.get(day), value=r?metrics[metric].get(r):null;
  if(typeof value==='number' && Number.isFinite(value) && value>=0){b.values.push(value);b.runs.push({date:day,run:r});}
 }
 return [...buckets.values()].map(b=>{const v=b.values.sort((a,b)=>a-b),n=v.length;return {...b,value:n?(v[Math.floor((n-1)/2)]+v[Math.floor(n/2)])/2:null};});
}
export function improvement(base,value,higher){return base>0 && Number.isFinite(value)?(value/base-1)*100*(higher?1:-1):null;}

// Causal policy: a confirmed baseline takes effect on confirmation day, never retroactively.
export function automaticBaseline(daily, higher, {threshold=5, required=3, maxSpan=7}={}) {
 const states=new Map(), stages=[], events=[];
 let seed=[], candidate=[], direction=0, baseline=null, initial=null;
 const median=points=>{const a=points.map(p=>p.value).sort((a,b)=>a-b);return a[Math.floor(a.length/2)];};
 for(const p of daily){
  let event=null;
  if(candidate.length && (Date.parse(p.date)-Date.parse(candidate[0].date))/86400000>=maxSpan){candidate=[];direction=0;}
  if(p.value!==null && Number.isFinite(p.value)){
   if(!baseline){
    seed.push(p);
    if(seed.length===required){
     baseline={date:p.date,start:seed[0].date,value:median(seed),number:1};initial=baseline;stages.push(baseline);
     event={type:'initial',date:p.date,start:seed[0].date,value:baseline.value};
    }
   }else{
    const delta=improvement(baseline.value,p.value,higher);
    const sign=delta!==null&&Math.abs(delta)>threshold?Math.sign(delta):0;
    if(!sign){candidate=[];direction=0;}
    else{
     if(sign!==direction){candidate=[];direction=sign;}
     candidate.push(p);
     if(candidate.length===required){
      event={type:sign>0?'improved':'regressed',date:p.date,start:candidate[0].date,value:median(candidate),previous:baseline.value};
      if(sign>0){baseline={date:p.date,start:candidate[0].date,value:event.value,number:stages.length+1};stages.push(baseline);}
      candidate=[];direction=0;
     }
    }
   }
  }
  if(event)events.push(event);
  states.set(p.date,{baseline,initial,event,candidate:direction,count:candidate.length,seedCount:seed.length});
 }
 return {states,stages,events,initial};
}

export function baselineHistory(runs,jobs,key,end,metric){
 const dates=jobs.map(dailyDate).filter(d=>d&&d<=end).sort();
 if(!dates.length)return automaticBaseline([],metrics[metric].higher);
 const days=Math.round((Date.parse(end)-Date.parse(dates[0]))/86400000)+1;
 return automaticBaseline(trendPoints(runs,jobs,key,end,'day',days,metric),metrics[metric].higher);
}
