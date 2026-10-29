// Keep job recency separate from the age of the last measured result.
export function overview(runs, jobs) {
  const ordered = [...jobs].sort((a,b) => Date.parse(b.started_at)-Date.parse(a.started_at));
  const byId = new Map(runs.map(r => [r.id,r]));
  return [...new Set(ordered.map(j => j.recipe_id))].map(id => {
    const history = ordered.filter(j => j.recipe_id === id);
    const measured = history.find(j => ['SUCCEEDED','SKIPPED'].includes(j.status) && byId.has(j.result_id));
    return {id, latest:history[0], measured, run:measured ? byId.get(measured.result_id) : null};
  });
}

// Per-run time per output token excludes the first token already timed by TTFT.
export function toptP90(run) {
  const samples = (run?.samples || []).filter(s => !s.warmup);
  if (!samples.length) return null;
  const values = samples.map(s => {
    if (s.status !== 0 || !Number.isFinite(s.decode_ms) || s.decode_ms < 0 ||
        !Number.isInteger(s.output_callbacks) || s.output_callbacks <= 1) return null;
    return s.decode_ms / (s.output_callbacks - 1);
  });
  if (values.some(v => v === null)) return null;
  values.sort((a,b) => a-b);
  return values[Math.ceil(values.length * 0.9) - 1];
}

// Kanban Prefill includes tokenizer + input evaluation + first-token sampling.
// The existing request-to-first-token measurement is exactly this public API boundary.
export function prefillP90(run) {
  const value = run.timing?.ttft_ms?.p90;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

// Rate at the P90 latency, not the P90 percentile of per-run rates.
export function prefillSpeed(run) {
  const duration = prefillP90(run), tokens = run.spec?.input_tokens;
  if (duration === null || duration <= 0 || typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) return null;
  return tokens * 1000 / duration;
}

// Show the quantization format only; packing/group details stay in archived evidence.
export function quantizationLabel(run) {
  let value = run.model?.quantization ?? run.spec?.quantization;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch {}
  }
  if (value && typeof value === 'object') value = value.format;
  const match = String(value ?? '').match(/S16S4|W4A16|Q4_K_M|Q4_0/i);
  return match ? match[0].toUpperCase() : '—';
}

// Link only to the recorded official artifact for this exact build.
export function buildVersionLink(record, runs = []) {
  const escape = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const commit = record.build_commit;
  const label = escape(commit?.slice(0,12));
  const daily = record.daily || runs.find(r => r.build_commit === commit && r.daily?.commit === commit)?.daily;
  if (!commit || daily?.commit !== commit) return label;
  try {
    const url = new URL(daily.source_url);
    if (url.protocol !== 'https:' || url.hostname !== 'repo.mindspore.cn' || url.port || url.username || url.password || !url.pathname.includes(`_${commit}_newest/`)) return label;
    return `<a href="${escape(url.href)}" target="_blank" rel="noopener noreferrer" title="在新标签页打开 Daily 归档发布件">${label}</a>`;
  } catch { return label; }
}
