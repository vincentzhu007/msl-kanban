// Resolve cascading categories while retaining a selected record on refresh/deep links.
const value = (run, key) => String(key === 'date' ? run.date || '未注明日期' : run.spec?.[key] || '未注明');
export function selectRecords(runs, requested = {}, selectedId) {
  const selected = runs.find(run => run.id === selectedId);
  const filters = {}, options = {};
  let candidates = runs.map((run, index) => ({run, index}));
  for (const key of ['date', 'model', 'soc']) {
    options[key] = [...new Set(candidates.map(({run}) => value(run, key)))].sort((a,b) => key === 'date' ? b.localeCompare(a) : a.localeCompare(b));
    const wanted = selected ? value(selected, key) : requested[key];
    filters[key] = options[key].includes(wanted) ? wanted : options[key][0] || '';
    candidates = candidates.filter(({run}) => value(run, key) === filters[key]);
  }
  const record = candidates.find(({run}) => run.id === selectedId) || candidates[0];
  return {filters, options, candidates, index: record?.index};
}
