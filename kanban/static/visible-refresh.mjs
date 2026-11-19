export const AUTO_REFRESH_MS = 15 * 60 * 1000;

export function autoRefreshTargets() {
  return { runs: AUTO_REFRESH_MS, jobs: 0 };
}

export function bindAutoRefresh(refresh, intervalMs = AUTO_REFRESH_MS, doc = globalThis.document) {
  if (!intervalMs) return () => {};
  return scheduleVisibleRefresh(refresh, intervalMs, doc);
}

function scheduleVisibleRefresh(refresh, intervalMs, doc) {
  let timer = 0;
  let running = false;
  let stopped = false;
  let last = Date.now();
  const hidden = () => Boolean(doc && doc.hidden);

  const clear = () => {
    if (!timer) return;
    clearTimeout(timer);
    timer = 0;
  };

  const arm = () => {
    clear();
    if (stopped || hidden() || running) return;
    const wait = Math.max(0, intervalMs - (Date.now() - last));
    timer = setTimeout(tick, wait);
  };

  const tick = async () => {
    timer = 0;
    if (stopped || hidden() || running) return;
    running = true;
    last = Date.now();
    try {
      await refresh();
    } catch {
    } finally {
      running = false;
      if (!stopped) arm();
    }
  };

  const onVisibility = () => arm();
  if (doc && typeof doc.addEventListener === 'function') {
    doc.addEventListener('visibilitychange', onVisibility);
  }
  arm();

  return () => {
    stopped = true;
    clear();
    if (doc && typeof doc.removeEventListener === 'function') {
      doc.removeEventListener('visibilitychange', onVisibility);
    }
  };
}
