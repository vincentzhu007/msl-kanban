export function visibleAuditText(record) {
  if (!record || record.record_kind !== 'independent_offline_revalidation' || record.new_device_run !== false) return [];
  const obs = record.observation || {};
  const samples = Array.isArray(obs.baseline_sample_kib) ? obs.baseline_sample_kib.join(', ') : '—';
  return [
    record.source || '',
    `决定 ${record.decision_at || '—'}`,
    `复核 ${record.revalidated_at || '—'}`,
    `原失败 ${record.evidence_actions_url || '—'}`,
    `job ${record.evidence_job_id || '—'}`,
    `原始总 PSS 稳定中位 ${obs.total_pss_stable_median_kib ?? '—'} KiB`,
    `基线样本 ${samples}`,
    `极差 ${obs.range_kib ?? '—'} KiB，阈值 ${obs.stability_limit_kib ?? '—'} KiB`,
    '已采集但不稳定',
    obs.warning_code === 'pss_baseline_unstable' ? '净 PSS 未计算' : '',
  ].filter(Boolean);
}
