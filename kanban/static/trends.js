import {metrics,trendGroups,trendPoints,improvement,baselineHistory} from './trends.mjs';
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v==null?'—':v.toFixed(2);
let records=[],tasks=[],end='';
$('trend-metric').innerHTML=Object.entries(metrics).map(([k,m])=>`<option value="${k}">${m.label}</option>`).join('');
export function updateTrends(runs,jobs,date){
 records=runs;tasks=jobs;end=date;
 const old=$('trend-series').value;
 const measuredIds=new Set(jobs.filter(j=>j.status==='SUCCEEDED').map(j=>j.result_id));
 const measured=runs.filter(r=>measuredIds.has(r.id)).sort((a,b)=>String(b.date).localeCompare(String(a.date)) || String(a.framework).localeCompare(String(b.framework)));
 $('trend-series').innerHTML=trendGroups(measured).map(g=>`<option value="${esc(g.key)}">${esc(g.label)}</option>`).join('');
 if([...$('trend-series').options].some(o=>o.value===old)) $('trend-series').value=old;
 draw();
}
function draw(){
 const metric=$('trend-metric').value,m=metrics[metric],grain=$('trend-grain').value;
 const points=trendPoints(records,tasks,$('trend-series').value,end,grain,Number($('trend-range').value),metric);
 const daily=trendPoints(records,tasks,$('trend-series').value,end,'day',Number($('trend-range').value),metric);
 const policy=baselineHistory(records,tasks,$('trend-series').value,end,metric);
 const state=policy.states.get(end),base=state?.baseline,initial=policy.initial;
 const valid=points.filter(p=>p.value!==null),last=valid.at(-1);
 const periodEnd=p=>grain==='day'?p.date: new Date(Math.min(Date.parse(p.date)+6*86400000,Date.parse(end))).toISOString().slice(0,10);
 const stageFor=p=>policy.states.get(periodEnd(p))?.baseline;
 const change=initial&&last?improvement(initial.value,last.value,m.higher):null;
 $('trend-baseline-heading').textContent=grain==='week'?'较周末阶段基线':'较当日阶段基线';
 $('trend-baseline').textContent=base?`自动基线 S${base.number}：${fmt(base.value)} ${m.unit} · ${base.start} 起采样，${base.date} 确认 · 初始基线 ${initial.date}：${fmt(initial.value)} ${m.unit}`:`建立基线中：${state?.seedCount||0} / 3 个有效日`;
 $('trend-change').textContent=change===null?'等待自动基线':`累计${change>=0?'改善':'回退'} ${Math.abs(change).toFixed(1)}% · 较初始基线${grain==='week'?'（最新周中位数）':''}`;
 $('trend-change').className=change===null?'muted':change>=0?'trend-good':'trend-bad';
 $('trend-note').textContent=`每个配置、每项指标独立计算：前 3 个有效日取中位数建立基线；连续 3 个有效日同向变化超过 5%，且首尾不超过 7 个自然日，确认变化。改善更新基线，回退保留基线。基线从完整历史计算，确认当日起生效，不随显示窗口滑动。橙色阶梯虚线为阶段基线；周视图显示周末基线，周指标为每日值的中位数。${m.unit}，越${m.higher?'高':'低'}越好。失败、复用与缺测不填充；未锁温/锁频，自动标记仅供观测。`;
 const eventNames={initial:'建立初始基线',improved:'确认改善 · 更新基线',regressed:'持续回退 · 保留基线'};
 const visibleEvents=policy.events.filter(e=>e.date>=daily[0]?.date);
 $('trend-events').innerHTML=visibleEvents.map(e=>`<span class="task-state ${e.type==='regressed'?'pending':'success'}">${e.date} ${eventNames[e.type]}（变化起点 ${e.start}）</span>`).join(' ') || '<span class="muted">当前窗口暂无已确认变化点</span>';
 if(state?.count) $('trend-events').innerHTML+=` <span class="task-state pending">候选${state.candidate>0?'改善':'回退'} ${state.count}/3 天 · 待确认</span>`;
 if(!valid.length){$('trend-chart').innerHTML='<p class="trend-empty">所选范围暂无有效实测，请切换配置或扩大时间范围。</p>';}
 else{
  const W=1040,H=290,L=80,R=25,T=28,B=48;
  let lo=Math.min(...valid.map(p=>p.value),...points.map(stageFor).filter(Boolean).map(b=>b.value)),hi=Math.max(...valid.map(p=>p.value),...points.map(stageFor).filter(Boolean).map(b=>b.value));
  const pad=(hi-lo)*.15 || Math.max(hi*.05,1);lo=Math.max(0,lo-pad);hi+=pad;
  const x=i=>L+i*(W-L-R)/Math.max(1,points.length-1), y=v=>H-B-(v-lo)/(hi-lo)*(H-T-B);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(m.label)}，${grain==='day'?'日':'周'}趋势"><title>${esc(m.label)}，详细数值见下表</title>`;
  for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e4ecef"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${fmt(v)}</text>`;}
  let baselinePath='';
  points.forEach((p,i)=>{const b=stageFor(p);if(!b)return;baselinePath+=`${baselinePath?'H'+x(i)+' V':'M'+x(i)+','}${y(b.value)} `;});
  svg+=`<path d="${baselinePath}" fill="none" stroke="#b97929" stroke-width="2" stroke-dasharray="7 5"/>`;
  for(const e of visibleEvents){const i=points.findIndex(p=>e.date>=p.date&&e.date<=periodEnd(p));if(i<0)continue;svg+=`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H-B}" stroke="#b97929" stroke-dasharray="2 5"><title>${e.date} ${eventNames[e.type]}，起点 ${e.start}</title></line>`;}
  let active=false,path='';
  points.forEach((p,i)=>{if(p.value===null){active=false;return;}path+=`${active?'L':'M'}${x(i)},${y(p.value)} `;active=true;});
  svg+=`<path d="${path}" fill="none" stroke="#168b80" stroke-width="3"/>`;
  points.forEach((p,i)=>{
   if(p.value!==null)svg+=`<circle cx="${x(i)}" cy="${y(p.value)}" r="4.5" fill="#168b80"><title>${p.date}: ${fmt(p.value)} ${m.unit}（${p.values.length} 个有效日）</title></circle>`;
   if(i%Math.max(1,Math.ceil(points.length/8))===0||i===points.length-1)svg+=`<text x="${x(i)}" y="${H-15}" text-anchor="middle">${p.date.slice(5)}</text>`;
  });
  $('trend-chart').innerHTML=svg+'</svg>';
 }
 const deltaLabel=v=>v===null?'—':`${v>=0?'改善':'回退'} ${Math.abs(v).toFixed(1)}%`;
 $('trend-history').innerHTML=[...points].reverse().map(p=>{
  const b=stageFor(p),dailyState=policy.states.get(p.date),established=grain==='day'&&['initial','improved'].includes(dailyState?.event?.type);
  const delta=b&&p.value!==null?improvement(b.value,p.value,m.higher):null;
  const total=b&&initial&&p.value!==null?improvement(initial.value,p.value,m.higher):null;
  return `<tr><td>${p.date}${grain==='week'?' 周':''}</td><td>${fmt(p.value)} ${esc(m.unit)}</td><td>${b?`S${b.number} · ${b.date}<br>${fmt(b.value)} ${esc(m.unit)}`:'积累中'}</td><td>${established?'基线确认':deltaLabel(delta)}</td><td>${deltaLabel(total)}</td><td>${p.values.length} / ${p.days} 天</td><td>${p.runs.map(({date,run})=>`<a target="_blank" rel="noopener noreferrer" href="detail.html?run=${encodeURIComponent(run.id)}">${date} · ${esc(run.build_commit?.slice(0,8)||'详情')} ↗</a>`).join(' · ')||'无有效实测'}</td></tr>`;
 }).join('');
}
for(const id of ['trend-series','trend-metric','trend-grain','trend-range']) $(id).addEventListener('change',draw);
