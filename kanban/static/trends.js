import {metrics,trendGroups,trendPoints,improvement,baselineHistory,trendTaskStates} from './trends.mjs';
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v==null?'—':v.toFixed(2);
let records=[],tasks=[],end='';
$('trend-metric').innerHTML=Object.entries(metrics).map(([k,m])=>`<option value="${k}">${m.label}</option>`).join('');
export function updateTrends(runs,jobs,date){
 records=runs;tasks=jobs;end=date;
 const old=$('trend-series').value;
 const measuredIds=new Set(jobs.filter(j=>j.status==='SUCCEEDED').map(j=>j.result_id));
 const backendRank=r=>r.backend?.name==='msl'||/MSL|MindSpore/i.test(r.framework||'')?0:/llama/i.test(r.framework||'')?2:1;
 const measured=runs.filter(r=>measuredIds.has(r.id)).sort((a,b)=>backendRank(a)-backendRank(b) || String(b.date).localeCompare(String(a.date)) || String(a.framework).localeCompare(String(b.framework)));
 $('trend-series').innerHTML=trendGroups(measured).map(g=>`<option value="${esc(g.key)}">${esc(g.label)}</option>`).join('');
 if([...$('trend-series').options].some(o=>o.value===old)) $('trend-series').value=old;
 draw();
}
function draw(){
 const metric=$('trend-metric').value,m=metrics[metric],grain=$('trend-grain').value;
 const points=trendPoints(records,tasks,$('trend-series').value,end,grain,Number($('trend-range').value),metric);
 const daily=trendPoints(records,tasks,$('trend-series').value,end,'day',Number($('trend-range').value),metric);
 const taskStates=trendTaskStates(records,tasks,$('trend-series').value);
 const policy=baselineHistory(records,tasks,$('trend-series').value,end,metric);
 const state=policy.states.get(end),base=state?.baseline,initial=policy.initial;
 const valid=points.filter(p=>p.value!==null),last=valid.at(-1);
 const periodEnd=p=>grain==='day'?p.date: new Date(Math.min(Date.parse(p.date)+6*86400000,Date.parse(end))).toISOString().slice(0,10);
 const stageFor=p=>policy.states.get(periodEnd(p))?.baseline;
 const change=initial&&last?improvement(initial.value,last.value,m.higher):null;
 $('trend-baseline-heading').textContent=grain==='week'?'较周末阶段基线':'较当日阶段基线';
 $('trend-baseline').textContent=base?`自动基线 S${base.number}：${fmt(base.value)} ${m.unit} · ${base.start} 起采样，${base.date} 确认 · 初始基线 ${initial.date}：${fmt(initial.value)} ${m.unit}`:`建立基线中：${state?.seedCount||0} / 3 个有效日`;
 $('trend-change').textContent=change===null?'等待自动基线':`累计${change>=0?'提升':'劣化'} ${Math.abs(change).toFixed(1)}% · 较初始基线${grain==='week'?'（最新周中位数）':''}`;
 $('trend-change').className=change===null?'muted':change>=0?'trend-good':'trend-bad';
 $('trend-note').innerHTML=`<span class="trend-key"><i class="key-line"></i> 实测性能</span><span class="trend-key"><i class="key-base"></i> 初始基线</span><span class="trend-key trend-good">● 改善 &gt;5%</span><span class="trend-key trend-bad">● 劣化 &gt;5%</span><span class="trend-key trend-bad">× 运行失败（非性能值）</span><span class="trend-key">○ 缺测 / 无有效指标</span><span class="trend-key">◇ 阻塞 / 运行中 / 复用</span><br>${m.unit}，越${m.higher?'高':'低'}越好 · 缺测处断线 · 周视图为有效日中位数 · 颜色相对当时阶段基线，累计幅度相对初始基线。`;
 const eventNames={initial:'基线',improved:'提升确认',regressed:'劣化确认'};
 const visibleEvents=policy.events.filter(e=>e.date>=daily[0]?.date);
 $('trend-events').innerHTML=visibleEvents.map(e=>{
  const delta=e.previous?improvement(e.previous,e.value,m.higher):null;
  return `<span class="trend-event ${e.type==='regressed'?'negative':'positive'}">${e.type==='initial'?`${e.date.slice(5)} 基线 · ${fmt(e.value)} ${esc(m.unit)}`:`${e.start.slice(5)} 起${e.type==='improved'?'提升':'劣化'} ${Math.abs(delta).toFixed(1)}% · ${e.date.slice(5)} 确认${e.type==='improved'?'，更新阶段基线':'，保留阶段基线'}`}</span>`;
 }).join(' ') || '<span class="muted">当前窗口暂无已确认变化点</span>';
 if(state?.count) $('trend-events').innerHTML+=` <span class="trend-event ${state.candidate>0?'positive':'negative'}">${state.candidate>0?'提升':'劣化'}待确认 · ${state.count}/3 个有效日</span>`;
 if(!valid.length){$('trend-chart').innerHTML='<p class="trend-empty">所选范围暂无有效实测，请切换配置或扩大时间范围。</p>';}
 else{
  const W=1040,H=360,L=80,R=45,T=44,B=88;
  const reference=initial?[initial.value]:[];
  let lo=Math.min(...valid.map(p=>p.value),...reference),hi=Math.max(...valid.map(p=>p.value),...reference);
  const pad=(hi-lo)*.2 || Math.max(hi*.05,1);lo=Math.max(0,lo-pad);hi+=pad;
  const x=i=>L+i*(W-L-R)/Math.max(1,points.length-1), y=v=>H-B-(v-lo)/(hi-lo)*(H-T-B);
  const deltaFor=p=>{const b=stageFor(p);return b&&p.value!==null?improvement(b.value,p.value,m.higher):null;};
  const color=p=>{const d=deltaFor(p);return d!==null&&d < -5?'#c34e48':d!==null&&d>5?'#09866a':'#376f83';};
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(m.label)}，${grain==='day'?'日':'周'}趋势，实测与失败状态分开展示"><title>${esc(m.label)}，详细数值见下表</title>`;
  for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e4ecef"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${fmt(v)}</text>`;}
  if(initial){
   const first=points.findIndex(p=>periodEnd(p)>=initial.date);
   if(first>=0)svg+=`<line x1="${x(first)}" x2="${W-R}" y1="${y(initial.value)}" y2="${y(initial.value)}" stroke="#b97929" stroke-width="1.5" stroke-dasharray="6 5"/><text x="${x(first)}" y="${y(initial.value)+19}" fill="#956222">${initial.date.slice(5)} 基线 ${fmt(initial.value)}</text>`;
  }
  // Color adjacent measured segments only; missing dates never get bridged.
  points.forEach((p,i)=>{
   if(p.value===null)return;
   const previous=points[i-1];
   if(previous?.value!==null&&previous?.value!==undefined)svg+=`<path d="M${x(i-1)},${y(previous.value)} L${x(i)},${y(p.value)}" fill="none" stroke="${color(p)}" stroke-width="3"/>`;
   svg+=`<circle cx="${x(i)}" cy="${y(p.value)}" r="5" fill="${color(p)}" stroke="white" stroke-width="1.5"><title>${p.date}: ${fmt(p.value)} ${m.unit}</title></circle>`;
   const d=deltaFor(p),prior=previous?deltaFor(previous):null;
   if(d!==null&&Math.abs(d)>5&&(prior===null||Math.sign(prior)!==Math.sign(d)||Math.abs(prior)<=5)){
    const anchor=i>points.length-3?'end':'start';
    svg+=`<text class="trend-annotation" x="${x(i)}" y="${Math.max(22,y(p.value)-18)}" text-anchor="${anchor}" style="fill:${color(p)}">${p.date.slice(5)} ${d>0?'提升':'劣化'} ${Math.abs(d).toFixed(1)}%</text>`;
   }
   if(p===last)svg+=`<text class="trend-annotation" x="${x(i)}" y="${y(p.value)+24}" text-anchor="end" style="fill:${color(p)}">${fmt(p.value)}</text>`;
  });
  svg+=`<line x1="${L}" x2="${W-R}" y1="${H-53}" y2="${H-53}" stroke="#e4ecef"/><text x="${L-10}" y="${H-49}" text-anchor="end">任务</text>`;
  points.forEach((p,i)=>{
   const jobs=[...taskStates].filter(([date])=>date>=p.date&&date<=periodEnd(p)).map(([,j])=>j);
   const failed=jobs.some(j=>j.status==='FAILED'||j.status==='CANCELLED');
   const blocked=jobs.some(j=>['BLOCKED','NO_BUILD','RUNNING','SKIPPED'].includes(j.status));
   const title=failed?'运行失败 / 已取消':blocked?'阻塞、运行中或复用结果':p.value===null?'缺测 / 无有效指标':'评测成功';
   svg+=`<text x="${x(i)}" y="${H-48}" text-anchor="middle" style="fill:${failed?'#c34e48':blocked?'#a46b1a':p.value===null?'#8798a2':'#09866a'};font-size:16px">${failed?'×':blocked?'◇':p.value===null?'○':'·'}<title>${p.date} ${title}</title></text>`;
   if(i%Math.max(1,Math.ceil(points.length/8))===0||i===points.length-1)svg+=`<text x="${x(i)}" y="${H-18}" text-anchor="middle">${p.date.slice(5)}</text>`;
  });
  $('trend-chart').innerHTML=svg+'</svg>';
 }
 const deltaLabel=v=>v===null?'—':`${v>=0?'提升':'劣化'} ${Math.abs(v).toFixed(1)}%`;
 $('trend-history').innerHTML=[...points].reverse().map(p=>{
  const b=stageFor(p),dailyState=policy.states.get(p.date),established=grain==='day'&&['initial','improved'].includes(dailyState?.event?.type);
  const delta=b&&p.value!==null?improvement(b.value,p.value,m.higher):null;
  const total=b&&initial&&p.value!==null?improvement(initial.value,p.value,m.higher):null;
  return `<tr><td>${p.date}${grain==='week'?' 周':''}${grain==='day'&&taskStates.get(p.date)?.status==='FAILED'?'<br><span class="trend-bad">运行失败</span>':''}</td><td>${fmt(p.value)} ${esc(m.unit)}</td><td>${b?`S${b.number} · ${b.date}<br>${fmt(b.value)} ${esc(m.unit)}`:'积累中'}</td><td>${established?(dailyState.event.type==='initial'?'基线':'阶段基线更新'):deltaLabel(delta)}</td><td>${deltaLabel(total)}</td><td>${p.values.length} / ${p.days} 天</td><td>${p.runs.map(({date,run})=>`<a target="_blank" rel="noopener noreferrer" href="detail.html?run=${encodeURIComponent(run.id)}">${date} · ${esc(run.build_commit?.slice(0,8)||'详情')} ↗</a>`).join(' · ')||'无有效实测'}</td></tr>`;
 }).join('');
}
for(const id of ['trend-series','trend-metric','trend-grain','trend-range']) $(id).addEventListener('change',draw);
