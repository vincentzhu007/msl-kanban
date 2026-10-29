import {overview} from './summary-model.mjs';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, scale=1, digits=2) => typeof v === 'number' && Number.isFinite(v) ? (v/scale).toFixed(digits) : '—';
const time = v => v ? new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '—';
const names = {SUCCEEDED:'成功',FAILED:'失败',BLOCKED:'依赖阻塞',SKIPPED:'复用已有结果',NO_BUILD:'暂无发布件',CANCELLED:'已取消',RUNNING:'运行中'};
const badge = j => `<span class="task-state ${j.status === 'SUCCEEDED' ? 'success' : 'pending'}">${esc(names[j.status] || j.status)}</span>`;
function row(item) {
  const {run:r,latest:j,measured} = item;
  const status = `${badge(j)}<small>任务 ${esc(time(j.started_at))}</small>`;
  if (!r) return `<tr><td>${esc(item.id.includes('cann-kit') ? 'CANN Kit LLM · Kirin9020' : item.id)}</td><td colspan="6">${esc(j.reason || '暂无有效实测记录')}</td><td>${status}</td></tr>`;
  const q = r.model?.quantization;
  const quant = q && typeof q === 'object' ? Object.entries(q).map(([k,v])=>`${k}: ${v}`).join(' · ') : r.spec.quantization;
  const stale = j.result_id !== r.id ? '<small class="warning">以下为历史实测，非最新任务产出</small>' : '';
  return `<tr><td><a href="detail.html?run=${encodeURIComponent(r.id)}">${esc(r.spec.model)}</a><small>${esc(r.framework)} · ${esc(r.spec.soc)}</small></td><td class="config-cell">${esc(quant)}<small>ctx ${esc(r.spec.context)} / in ${esc(r.spec.input_tokens)} / out ${esc(r.spec.output_tokens)} · ${esc(r.spec.consecutive_runs)} 次</small></td><td>${num(r.model?.bytes,1048576)}</td><td>${num(r.memory?.total_pss_kib?.stable_median,1024)} / ${num(r.memory?.total_pss_kib?.sampled_peak,1024)}<small>稳定采样 ${esc(r.memory?.stable_samples)} 个</small></td><td class="muted">未单独采集</td><td>${num(r.timing?.ttft_ms?.p90,1000,3)}</td><td>${num(r.timing?.decode_tps?.median)}</td><td>${status}${stale}<small>实测 ${esc(r.date)}<br>版本 ${esc(r.build_commit?.slice(0,12))}</small><a href="detail.html?run=${encodeURIComponent(r.id)}">查看记录 →</a></td></tr>`;
}
async function refresh() {
  $('summary-refresh').disabled = true;
  try {
    const [a,b] = await Promise.all([fetch('/api/runs'),fetch('/api/jobs')]);
    if (!a.ok || !b.ok) throw Error('数据暂不可用');
    const [runs,jobs] = await Promise.all([a.json(),b.json()]);
    const items = overview(runs,jobs);
    const msl = items.filter(x => x.id.includes('-msl-'));
    const competitors = items.filter(x => !x.id.includes('-msl-'));
    const empty = '<tr><td colspan="8">暂无 Daily 记录</td></tr>';
    $('msl-summary').innerHTML = msl.map(row).join('') || empty;
    $('competitor-summary').innerHTML = competitors.map(row).join('') || empty;
    $('summary-status').textContent = `${items.length} 项任务 · ${items.filter(x=>x.run).length} 项有实测 · 更新于 ${time(new Date().toISOString())}`;
    $('summary-jobs').innerHTML = [...jobs].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)).slice(0,30).map(j=>`<tr><td>${esc(time(j.started_at))}</td><td>${esc(j.recipe_id)}</td><td>${badge(j)}</td><td>${esc(j.stage)}<small>${esc(j.reason || '')}</small></td><td>${/^https:\/\/github\.com\/[^/]+\/[^/]+\/actions\/runs\/\d+$/.test(j.task_url || '') ? `<a href="${esc(j.task_url)}" target="_blank" rel="noopener">查看日志</a>` : '—'}</td></tr>`).join('');
    $('summary-error').textContent = '';
  } catch (e) { $('summary-error').textContent = `加载失败：${e.message}。已有表格可能过期，请刷新重试。`; }
  finally { $('summary-refresh').disabled = false; }
}
$('summary-refresh').onclick = refresh;
refresh(); setInterval(refresh,60000);
