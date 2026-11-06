import {updateTrends} from './trends.js';
import {selectDaily, tpotP90, prefillSpeed, quantizationLabel, buildVersionLink} from './summary-model.mjs';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, scale=1, digits=2) => typeof v === 'number' && Number.isFinite(v) ? (v/scale).toFixed(digits) : '—';
const time = v => v ? new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '—';
const names = {SUCCEEDED:'成功',FAILED:'失败',BLOCKED:'依赖阻塞',SKIPPED:'复用已有结果',NO_BUILD:'暂无发布件',CANCELLED:'已取消',RUNNING:'运行中'};
const badge = j => `<span class="task-state ${j.status === 'SUCCEEDED' ? 'success' : 'pending'}">${esc(names[j.status] || j.status)}</span>`;
function row(item) {
  const {run:r,latest:j,measured} = item;
  const status = `${badge(j)}<small>任务 ${esc(time(j.started_at))}</small>`;
  if (!r) return `<tr><td>—</td><td>${item.id.includes('cann-kit') ? 'Kirin9020' : '—'}</td><td class="config-cell">${esc(item.id.includes('cann-kit') ? 'CANN Kit LLM' : item.id)}</td><td colspan="7">${esc(j.reason || '暂无有效实测记录')}</td><td>${status}</td><td>—</td></tr>`;
  const quant = quantizationLabel(r);
  const options = r.backend?.options || {};
  const backendConfig = Object.entries(options).map(([k,v]) => `${k}: ${v}`).join(' · ');
  const stale = j.result_id !== r.id ? '<small class="warning">以下为历史实测，非最新任务产出</small>' : '';
  return `<tr><td><a href="detail.html?run=${encodeURIComponent(r.id)}">${esc(r.spec.model)}</a></td><td>${esc(r.spec.soc)}</td><td class="config-cell"><strong>${esc(r.framework)}</strong>${backendConfig ? `<small>${esc(backendConfig)}</small>` : ''}<small>${esc(quant)}</small></td><td>${num(r.model?.bytes,1048576)}</td><td>${num(r.memory?.total_pss_kib?.stable_median,1024)} / ${num(r.memory?.total_pss_kib?.sampled_peak,1024)}<small>稳定采样 ${esc(r.memory?.stable_samples)} 个</small></td><td>${num(r.initialization?.model_init_ms,1000,3)}</td><td>${num(r.timing?.ttft_ms?.p90,1000,3)}</td><td>${num(tpotP90(r))}</td><td>${num(prefillSpeed(r))}<small>按 TTFT P90 换算</small></td><td>${num(r.timing?.decode_tps?.p90)}</td><td>${status}${stale}<small>实测 ${esc(r.date)}<br>版本 ${buildVersionLink(r)}</small></td><td><a href="detail.html?run=${encodeURIComponent(r.id)}" target="_blank" rel="noopener noreferrer" title="在新标签页查看评测详情">查看评测详情 ↗</a></td></tr>`;
}
let records = [], tasks = [];
let selectedDate = new URL(location.href).searchParams.get('date') || '';
function render() {
    const {dates,date,jobs,items} = selectDaily(records,tasks,selectedDate);
    selectedDate = date;
    updateTrends(records,tasks,date);
    $('summary-date').innerHTML = dates.length ? dates.map(d => `<option value="${d}">${d}${d === dates[0] ? ' · 最新' : ''}</option>`).join('') : '<option value="">暂无 Daily 记录</option>';
    $('summary-date').value = date;
    $('summary-date').disabled = !dates.length;
    const url = new URL(location.href);
    if (date) url.searchParams.set('date',date); else url.searchParams.delete('date');
    history.replaceState(null,'',url);
    const protocols = new Map();
    for (const {run:r} of items) {
      if (!r) continue;
      const s = r.spec;
      const label = `上下文 ${s.context ?? '—'} tokens · 输入 ${s.input_tokens ?? '—'} tokens · 输出 ${s.output_tokens ?? '—'} tokens · 连续推理 ${s.consecutive_runs ?? '—'} 次`;
      if (!protocols.has(label)) protocols.set(label, []);
      protocols.get(label).push(`${s.model} / ${s.soc} / ${r.framework}`);
    }
    $('summary-protocol').textContent = protocols.size
      ? [...protocols].map(([label,models]) => label + (protocols.size > 1 ? `（适用：${models.join('；')}）` : '')).join('；\n')
      : '暂无有效实测，测试规格待记录发布后展示。';
    const msl = items.filter(x => x.id.includes('-msl-'));
    const competitors = items.filter(x => !x.id.includes('-msl-'));
    const empty = '<tr><td colspan="12">暂无 Daily 记录</td></tr>';
    $('msl-summary').innerHTML = msl.map(row).join('') || empty;
    $('competitor-summary').innerHTML = competitors.map(row).join('') || empty;
    $('summary-status').textContent = `${date || '暂无日期'} · ${items.length} 项任务 · ${items.filter(x=>x.run).length} 项有实测 · 更新于 ${time(new Date().toISOString())}`;
    $('summary-jobs').innerHTML = [...jobs].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)).slice(0,30).map(j=>`<tr><td>${esc(time(j.started_at))}</td><td>${esc(j.recipe_id)}</td><td>${badge(j)}</td><td>${esc(j.stage)}<small>${esc(j.reason || '')}</small></td><td>${/^https:\/\/github\.com\/[^/]+\/[^/]+\/actions\/runs\/\d+$/.test(j.task_url || '') ? `<a href="${esc(j.task_url)}" target="_blank" rel="noopener">查看日志</a>` : '—'}</td></tr>`).join('');
}
async function refresh() {
  $('summary-refresh').disabled = true;
  try {
    const [a,b] = await Promise.all([fetch('/api/runs'),fetch('/api/jobs')]);
    if (!a.ok || !b.ok) throw Error('数据暂不可用');
    [records,tasks] = await Promise.all([a.json(),b.json()]);
    render();
    $('summary-error').textContent = '';
  } catch (e) { $('summary-error').textContent = `加载失败：${e.message}。已有表格可能过期，请刷新重试。`; }
  finally { $('summary-refresh').disabled = false; }
}
$('summary-date').onchange = () => { selectedDate = $('summary-date').value; render(); };
$('summary-refresh').onclick = refresh;
refresh(); setInterval(refresh,60000);
