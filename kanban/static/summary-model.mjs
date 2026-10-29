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
