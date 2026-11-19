import {dailyDate, prefillSpeed, tpotP90, quantizationLabel} from './summary-model.mjs';
import {netPssKind} from './ram-method.mjs';
export const metrics = {
 decode: {label:'Decode 速度（P90）',unit:'token/s',higher:true,get:r=>r.timing?.decode_tps?.p90},
 prefill: {label:'Prefill 速度（P90 时延换算）',unit:'token/s',higher:true,get:prefillSpeed},
 ttft: {label:'TTFT P90',unit:'ms',get:r=>r.timing?.ttft_ms?.p90},
 tpot: {label:'TPOT P90',unit:'ms/token',get:tpotP90},
 ram: {label:'RAM · 扣底噪稳定 PSS',unit:'MiB',get:r=>netPssKind(r.memory)==='net' && r.memory.net_pss_kib.stable_median != null ? r.memory.net_pss_kib.stable_median/1024 : null},
 ram_raw: {label:'RAM · 原始总 PSS（未扣除）',unit:'MiB',get:r=>r.memory?.total_pss_kib?.stable_median == null ? null : r.memory.total_pss_kib.stable_median/1024},
 rom: {label:'ROM',unit:'MiB',get:r=>r.model?.bytes == null ? null : r.model.bytes/1048576},
 init: {label:'模型初始化',unit:'ms',get:r=>r.initialization?.model_init_ms}
};
const canonical = x => x && typeof x==='object' ? Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])) : x;
// RAM methodology affects memory comparability, not deployment identity.
export const ramMethod = r => r.memory?.ram_method ?? null;
export function seriesKey(r) {
 const s=r.spec || {};
 // Trend identity follows the visible deployment and workload, not archive metadata or sample count.
 return JSON.stringify(canonical({model:s.model,soc:s.soc,framework:r.framework,quant:quantizationLabel(r),context:s.context,input:s.input_tokens,output:s.output_tokens}));
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
// Select the latest successful RAM methodology as of the selected date, independent of window size.
export function trendRamMethod(runs,jobs,key,end) {
 const byId=new Map(runs.map(r=>[r.id,r]));
 const latest=[...jobs].filter(j=>j.status==='SUCCEEDED' && dailyDate(j)<=end && byId.has(j.result_id) && seriesKey(byId.get(j.result_id))===key)
  .sort((a,b)=>dailyDate(b).localeCompare(dailyDate(a)) || Date.parse(b.started_at)-Date.parse(a.started_at))[0];
 return latest?ramMethod(byId.get(latest.result_id)):null;
}
export function trendPoints(runs,jobs,key,end,grain='day',windowDays=30,metric='decode') {
 if(!end || !metrics[metric]) return [];
 const start=shift(end,1-windowDays), byId=new Map(runs.map(r=>[r.id,r])), daily=new Map();
 // Only successful measurements, never reused results or historical fallback.
 for(const j of [...jobs].sort((a,b)=>Date.parse(a.started_at)-Date.parse(b.started_at))){
  const date=dailyDate(j),r=byId.get(j.result_id);
  if(j.status==='SUCCEEDED' && r && seriesKey(r)===key && date>=start && date<=end) daily.set(date,r);
 }
 const method=metric==='ram'?trendRamMethod(runs,jobs,key,end):null;
 const buckets=new Map();
 for(let day=start;day<=end;day=shift(day,1)){
  const period=grain==='week'?weekStart(day):day;
  if(!buckets.has(period)) buckets.set(period,{date:period,days:0,runs:[],values:[]});
  const b=buckets.get(period); b.days++;
  const r=daily.get(day), value=r && (metric!=='ram' || ramMethod(r)===method)?metrics[metric].get(r):null;
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

// Task failures are execution state, never a zero performance sample.
export function trendTaskStates(runs,jobs,key){
 const recipes=new Set(runs.filter(r=>seriesKey(r)===key).map(r=>r.recipe_id).filter(Boolean));
 const dates=new Map();
 for(const job of [...jobs].sort((a,b)=>Date.parse(a.started_at)-Date.parse(b.started_at))){
  if(!recipes.has(job.recipe_id))continue;
  const date=dailyDate(job);if(date)dates.set(date,job);
 }
 return dates;
}


// Keep a meaningful baseline-centered range; five-percent changes remain visible.
export function trendScale(values, metric, reference){
 const finite=values.filter(v=>Number.isFinite(v)&&v>=0);
 if(!finite.length)return {min:0,max:1,step:0.25,ticks:[0,0.25,0.5,0.75,1]};
 const low=Math.min(...finite),high=Math.max(...finite);
 const center=Number.isFinite(reference)&&reference>0?reference:(low+high)/2;
 let min,max;
 if(metric==='rom'){
  const span=Math.max(center*.2,1);
  min=Math.max(0,Math.min(center-span/2,low-span*.05));
  max=Math.max(center+span/2,high+span*.05);
 }
 else{
  const span=Math.max(high-low,center*.2,metric==='ram'?64:1);
  min=Math.max(0,Math.min(low-span*.1,center-span/2));
  max=Math.max(high+span*.1,center+span/2);
 }
 const raw=(max-min)/4,power=10**Math.floor(Math.log10(raw));
 const step=([1,2,2.5,5,10].find(n=>n*power>=raw)||10)*power;
 min=Math.floor(min/step)*step;max=Math.ceil(max/step)*step;
 const ticks=[];for(let v=min;v<=max+step*.001;v+=step)ticks.push(Number(v.toPrecision(12)));
 return {min,max,step,ticks};
}

// Tolerance avoids missing the exact 10% boundary through floating-point rounding.
export function isBugRegression(delta){return Number.isFinite(delta)&&delta<=-10+1e-9;}
