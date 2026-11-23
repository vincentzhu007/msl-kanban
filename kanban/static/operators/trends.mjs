export function versionKey(record) {
  return record.commit ?? record.source_sha256;
}

export function versionLabel(record) {
  const prefix = record.commit ? '' : '快照 ';
  return prefix + versionKey(record).slice(0, 7);
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function measurement(item, column) {
  const rounds = item.case.runs;
  const samples = rounds.map(run => run.hot.map(sample => sample[column]));
  return median(item.record.statistic === 'hot-samples-median' ? samples.flat() : samples.map(median));
}

export function samplePoints(items, axis, column) {
  if (axis === 'run') {
    return items.flatMap(item => item.case.runs.flatMap(run => run.hot.map((sample, index) => ({
      value: sample[column], item, run, sample, index
    })))).filter(point => Number.isFinite(point.value)).sort((a, b) => (
      a.item.record.date.localeCompare(b.item.record.date) || a.sample[0].localeCompare(b.sample[0])
    ));
  }
  const latest = new Map();
  for (const item of items) {
    const value = measurement(item, column);
    if (value === null) continue;
    const key = axis === 'day' ? item.record.date : versionKey(item.record);
    latest.set(key, {value, item});
  }
  return [...latest.values()].sort((a, b) => (
    a.item.record.date.localeCompare(b.item.record.date) || a.item.order - b.item.order
  ));
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
}

export function environmentKey({record, case: item}) {
  // Historical campaigns are explicitly grouped by their recorded environment.
  // New imports can record the full test configuration in environment.
  return JSON.stringify(canonical([record.platform, record.device, record.system, record.mode,
    record.protocol, record.environment, item.spec]));
}

export function dimensions(spec) {
  const values = Object.entries(spec.dimensions ?? {}).map(([name, size]) => name + '=' + size);
  for (const item of spec.inputs ?? []) {
    values.push([item.name, Array.isArray(item.shape) ? '[' + item.shape.join(', ') + ']' : '',
      item.dtype, item.layout].filter(Boolean).join(' '));
  }
  for (const [name, value] of Object.entries(spec.attrs ?? {})) {
    values.push(name + '=' + (typeof value === 'object' ? JSON.stringify(value) : value));
  }
  return values.join(' · ');
}
