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
