import {mobileKanbanRecords, prefillSpeed, quantizationLabel, buildVersionLink} from './summary-model.mjs';
import {selectRecords} from './detail-filters.mjs';
import {baselineLabel, netPssKind, ramComparable, RAM_MISMATCH} from './ram-method.mjs';
const $=id=>document.getElementById(id),esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let runs=[],current,local=[];try{local=JSON.parse(localStorage.getItem('edge-imports')||'[]')}catch{}
const n=(v,d=2)=>Number.isFinite(Number(v))?Number(v).toFixed(d):'—';const mib=v=>n(v/1024);const stat=(r,key)=>r.timing?.[key]||{};
function chart(series,labels){let w=580,h=220,p=42,max=Math.max(1,...series.flatMap(s=>s.values))*1.15;let len=Math.max(1,labels.length-1);let out='';for(let i=0;i<=4;i++){let y=h-p-(h-2*p)*i/4;out+=`<line x1="${p}" x2="${w-12}" y1="${y}" y2="${y}" stroke="#e9eff2"/><text x="${p-7}" y="${y+4}" text-anchor="end" fill="#81939d" font-size="10">${Math.round(max*i/4)}</text>`}series.forEach(s=>{out+=`<polyline fill="none" stroke="${s.color}" stroke-width="2.5" points="${s.values.map((v,i)=>`${p+i*(w-p-12)/len},${h-p-v/max*(h-2*p)}`).join(' ')}"/>`;s.values.forEach((v,i)=>out+=`<circle cx="${p+i*(w-p-12)/len}" cy="${h-p-v/max*(h-2*p)}" r="3" fill="${s.color}"><title>${esc(labels[i])}: ${n(v)}</title></circle>`)});labels.forEach((l,i)=>{if(i%Math.max(1,Math.ceil(labels.length/7))===0||i===labels.length-1)out+=`<text x="${p+i*(w-p-12)/len}" y="${h-15}" fill="#81939d" font-size="10" text-anchor="middle">${esc(l)}</text>`});return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="指标曲线">${out}</svg>`}
function render(){current=runs[+$('run').value];if(!current)return;let r=current,s=r.spec,mem=r.memory||{};let g=mem.graph_kib||{},t=mem.total_pss_kib||{};let kind=netPssKind(mem);$('total').innerHTML=n(stat(r,'total_ms').p90/1000,3)+' <small>s</small>';$('ttft').innerHTML=n(stat(r,'ttft_ms').p90/1000,3)+' <small>s</small>';$('speed').innerHTML=n(stat(r,'decode_tps').median)+' <small>token/s</small>';$('graph').innerHTML=mib(mem.net_pss_kib?.stable_median)+' <small>MiB</small>';$('graph').closest('.card').querySelector('.label').textContent=kind==='not_calculated'?'扣底噪 PSS · 未计算':'扣底噪 PSS · 稳定中位数';$('graphpeak').textContent=kind==='not_calculated'?'净 PSS 未计算 · 底噪中位 '+mib(mem.baseline_pss_kib?.median)+' MiB · 极差 '+mib(mem.baseline_pss_kib?.range_kib)+' MiB':kind==='net'?'底噪 '+mib(mem.baseline_pss_kib.median)+' MiB · 净峰值 '+mib(mem.net_pss_kib.sampled_peak)+' MiB':'未采集底噪 · 原始稳定 PSS '+mib(t.stable_median)+' MiB';
let rows=r.samples||[];$('latency').innerHTML=chart([{color:'#1ca78d',values:rows.map(x=>x.total_ms)},{color:'#4486d3',values:rows.map(x=>x.ttft_ms)}],rows.map(x=>'#'+x.run));let mm=r.memory_samples||[];$('memory').innerHTML=mm.length?chart([{color:'#1ca78d',values:mm.map(x=>x.total_pss_kib/1024)},{color:'#4486d3',values:mm.map(x=>x.graph_kib/1024)}],mm.map(x=>n((x.start_epoch_ms-mm[0].start_epoch_ms)/1000,1)+'s')):'<p class="note">未提供内存时间线</p>';
let fields={'模型':s.model,'量化规格':quantizationLabel(r),'设备 / 芯片':`${r.device||'—'} / ${s.soc}`,'框架':r.framework,'上下文 / 输入 / 输出':`${s.context} / ${s.input_tokens} / ${s.output_tokens}`,'推理次数':`${s.consecutive_runs} 次连续`,'模型初始化 · 单次':r.initialization? n(r.initialization.model_init_ms/1000,3)+' s':'未采集','Prefill 速度（按 TTFT P90）':prefillSpeed(r)!==null?n(prefillSpeed(r))+' token/s':'未采集','模型 ROM':r.model?.bytes?mib(r.model.bytes/1024)+' MiB':'—','构建版本':r.build_commit?.slice(0,12)};$('spec').innerHTML=Object.entries(fields).map(([k,v])=>`<div class="muted">${esc(k)}<b style="color:#233e4b">${k==='构建版本'?buildVersionLink(r):esc(v)}</b></div>`).join('');$('protocol').textContent=r.protocol_note||(r.id==='20261026-kirin9020-qwen25-05b'?'原始合成输入，greedy 生成；同进程无间隔执行 5 次。使用每日运行库与已有 2K 模型，模型仅补充兼容标识，资源字节一致。同步采集内存，采样开销未扣除；温度与频率未锁定。':'导入数据：请核对原始测试协议、采样口径和来源。');
$('memtable').innerHTML=[['Graph / NPU（原始）',g],['总 PSS（原始）',t],[kind==='not_calculated'?'净 PSS（未计算）':`PSS（${baselineLabel(mem.ram_method)}）`,kind==='not_calculated'?{}:(mem.net_pss_kib||{})]].map(([k,v])=>`<tr><td>${k}</td><td>${mib(v.sampled_peak)}</td><td>${mib(v.inference_sampled_peak)}</td><td>${mib(v.stable_median)} MiB</td></tr>`).join('');$('samples').innerHTML=rows.map(x=>`<tr><td>#${esc(x.run)}</td><td>${n(x.total_ms)}</td><td>${n(x.ttft_ms)}</td><td>${n(x.decode_tps)}</td><td>${esc(x.output_callbacks)}</td></tr>`).join('');$('compare').innerHTML=runs.map(x=>{let z=x.spec,same=['context','input_tokens','output_tokens','soc','consecutive_runs'].every(k=>z[k]===s[k]);return `<tr><td>${esc(z.model)}<br><span class="muted">${esc(x.framework)}</span></td><td>${esc(z.soc)}</td><td>${esc(z.context)} / ${esc(z.input_tokens)} / ${esc(z.output_tokens)}</td><td>${n(stat(x,'total_ms').p90/1000,3)} s</td><td>${n(stat(x,'ttft_ms').p90/1000,3)} s</td><td>${mib(x.memory?.net_pss_kib?.stable_median)} MiB<br><span class="muted">${esc(baselineLabel(x.memory?.ram_method))}</span>${netPssKind(x.memory)==='not_calculated'?'<br>净 PSS 未计算':''}${ramComparable(x,r)?'':'<br><strong>'+RAM_MISMATCH+'</strong>'}</td><td>${esc(x.source)}</td><td>${same?'规格匹配 · 需核对协议':'规格不同'}</td></tr>`}).join('')}
let filters = {};
function showRecord() {
  const index = $('run').value;
  current = index === '' ? undefined : runs[Number(index)];
  $('result-content').hidden = !current;
  $('export').disabled = !current;
  $('record-id').textContent = current ? `记录 ID：${current.id}` : '暂无评测结果';
  const url = new URL(location.href);
  if (current) url.searchParams.set('run', current.id); else url.searchParams.delete('run');
  history.replaceState(null, '', url);
  if (current) {render(); renderTrend();}
}
function updateFilters(selectedId) {
  const state = selectRecords(runs, filters, selectedId);
  filters = state.filters;
  for (const [key, id] of [['date','filter-date'], ['model','filter-model'], ['soc','filter-chip']]) {
    $(id).innerHTML = state.options[key].map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    $(id).value = filters[key];
    $(id).disabled = !state.options[key].length;
  }
  $('run').innerHTML = state.candidates.map(({run:r,index}) => {
    const framework = r.framework === 'MindSpore Lite LLM' ? 'MSL-LLM NPU' : r.framework;
    const quant = quantizationLabel(r);
    return `<option value="${index}">${esc(framework)} · ${esc(quant)} · ${esc(r.spec.consecutive_runs)} 次 · ${esc(r.id.split('-').slice(-2).join('-'))}${local.some(x=>x.id===r.id)?' · 导入':''}</option>`;
  }).join('');
  $('run').disabled = !state.candidates.length;
  $('run').value = state.index ?? '';
  $('filter-count').textContent = `${state.candidates.length} 条匹配 / ${runs.length} 条记录`;
  showRecord();
}
for (const [key,id] of [['date','filter-date'],['model','filter-model'],['soc','filter-chip']]) {
  $(id).onchange = () => {filters[key] = $(id).value; updateFilters();};
}
async function refresh(selectedId) {
  try {
    const response = await fetch('/api/runs');
    if (!response.ok) throw Error('服务暂不可用');
    const keep = typeof selectedId === 'string' ? selectedId : current?.id || new URLSearchParams(location.search).get('run');
    const remote = mobileKanbanRecords(await response.json());
    runs = [...remote, ...local].sort((a,b)=>String(b.date).localeCompare(String(a.date))||String(b.id).localeCompare(String(a.id)));
    updateFilters(keep);
    $('status').textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN')} · 每 60 秒自动刷新`;
    $('error').textContent = keep && !runs.some(r=>r.id===keep) ? '原记录已不可用，已显示当前可用结果。' : '';
  } catch(e) {$('error').textContent = '加载失败：'+e.message;}
}
$('run').onchange=showRecord;$('refresh').onclick=refresh;$('export').onclick=()=>{if(!current)return;let a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:'application/json'}));a.href=url;a.download='edge-slm-result.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};$('clear').onclick=()=>{local=[];localStorage.removeItem('edge-imports');refresh()};$('import').onchange=async e=>{try{let f=e.target.files[0];if(!f)return;if(f.size>5e6)throw Error('文件不得超过 5 MB');let r=JSON.parse(await f.text());if(!r.spec||!r.timing||!Array.isArray(r.samples)||!r.samples.length)throw Error('需要 spec、timing 和非空 samples 字段，请参考导出格式');for(let k of ['total_ms','ttft_ms','decode_tps'])if(!Number.isFinite(r.timing[k]?.p90)||!Number.isFinite(r.timing[k]?.median))throw Error('缺少数值指标 '+k);r.id='import-'+Date.now();r.source=r.source||'手动导入 · 未验证';local.push(r);localStorage.setItem('edge-imports',JSON.stringify(local));await refresh(r.id)}catch(e){$('error').textContent='导入失败：'+e.message}finally{e.target.value=''}};refresh();setInterval(refresh,60000);

async function refreshJobs(){
  try {
    const response=await fetch('/api/jobs');
    if(!response.ok)throw Error('任务记录不可用');
    const jobs=mobileKanbanRecords(await response.json());
    const names={SUCCEEDED:'评测成功',FAILED:'失败',SKIPPED:'已有有效结果',NO_BUILD:'暂无发布件',CANCELLED:'已取消',RUNNING:'运行中',BLOCKED:'依赖阻塞'};
    $('jobs').innerHTML=jobs.sort((a,b)=>String(b.started_at).localeCompare(String(a.started_at))).slice(0,30).map(j=>{
      const safe=/^https:\/\/github\.com\/vincentzhu007\/msl-kanban\/actions\/runs\/[0-9]+$/.test(j.task_url||'');
      return `<tr><td>${esc(j.started_at)}</td><td>${esc(j.recipe_id||'—')}</td><td>${buildVersionLink(j,runs)}</td><td>${esc(names[j.status]||j.status)}${j.reason?`<br><small>${esc(j.reason)}</small>`:''}</td><td>${esc(j.stage)}</td><td>${safe?`<a href="${esc(j.task_url)}" target="_blank" rel="noopener">查看日志</a>`:'—'}</td></tr>`;
    }).join('')||'<tr><td colspan="6">暂无 Daily 任务记录</td></tr>';
  } catch(e){$('jobs').innerHTML='<tr><td colspan="6">'+esc(e.message)+'</td></tr>'}
}
function renderTrend(){
  const group=current?.device_comparison_key?runs.filter(r=>r.device_comparison_key===current.device_comparison_key).sort((a,b)=>String(a.date).localeCompare(String(b.date))||String(a.id).localeCompare(String(b.id))):[];
  $('trend').innerHTML=group.length?chart([{color:'#1ca78d',values:group.map(r=>r.timing.total_ms.p90)}],group.map(r=>r.date+' / '+r.build_commit.slice(0,7))):'<p class="note">当前结果尚无完整设备比较指纹。</p>';
}
refreshJobs();setInterval(refreshJobs,60000);
