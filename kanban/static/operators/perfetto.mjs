const VIEWER_URL = '/operators/viewer/v59.1-491832c0d/index.html';

export function createTraceViewer($, dataRoot, escape) {
  const container = $('viewer');
  const grip = $('viewer-grip');
  const status = $('trace-status');
  const mode = $('trace-mode');
  let trace, label, traceKey, pending, frame;

  function close() {
    pending?.abort();
    pending = null;
    frame = null;
    container.replaceChildren();
    grip.hidden = true;
  }

  function selectedFile() {
    return trace[mode.value]?.file ?? trace.file;
  }

  function updateControls() {
    close();
    const file = selectedFile();
    $('download-trace').href = dataRoot + file;
    $('download-trace').download = label.replace(/[\\/:*?"<>|]/g, '-') +
      '-' + mode.value + (file.endsWith('.gz') ? '.json.gz' : '.json');
    $('open-trace').disabled = false;
    status.textContent = mode.value === 'lifecycle' ? 'pop 和 retire 轨道位于对应流水的 BUSY 下方。' : '';
  }

  async function open() {
    close();
    pending = new AbortController();
    const {signal} = pending;
    $('open-trace').disabled = true;
    status.textContent = '正在载入 Perfetto…';
    try {
      const viewer = await fetch(VIEWER_URL, {method: 'HEAD', signal});
      if (!viewer.ok) throw new Error('本环境未配置内嵌查看器，可下载流水文件');
      const response = await fetch(dataRoot + selectedFile(), {signal});
      if (!response.ok) throw new Error('流水文件请求失败（HTTP ' + response.status + '）');
      const data = new Uint8Array(await response.arrayBuffer());
      const blob = new Blob([data]);
      const buffer = data[0] === 31 && data[1] === 139
        ? await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
        : await blob.arrayBuffer();
      if (signal.aborted) return;
      const iframe = document.createElement('iframe');
      iframe.title = label + ' · Perfetto 流水';
      iframe.src = VIEWER_URL + '#!/?mode=embedded';
      iframe.allowFullscreen = true;
      frame = iframe;
      container.replaceChildren(iframe);
      grip.hidden = false;
      const ping = setInterval(() => iframe.contentWindow?.postMessage('PING', location.origin), 150);
      let poll;
      const timeout = setTimeout(() => {
        cleanup();
        status.textContent = '查看器加载超时，可重试或下载流水文件。';
        $('open-trace').disabled = false;
      }, 90000);
      function reply(event) {
        if (event.origin !== location.origin || event.source !== iframe.contentWindow ||
            event.data !== 'PONG' || signal.aborted) return;
        clearInterval(ping);
        window.removeEventListener('message', reply);
        iframe.contentWindow.postMessage({
          perfetto: {buffer, title: iframe.title, fileName: 'trace.json', keepApiOpen: true}
        }, location.origin, [buffer]);
        status.textContent = '已交给 Perfetto，正在解析流水…';
        poll = setInterval(() => {
          if (!iframe.contentDocument?.querySelector('.pf-timeline, .pf-track-tree, .pf-timeline-header, [ref="timeline"]')) return;
          cleanup();
          status.textContent = 'Perfetto 流水已载入。';
          $('open-trace').disabled = false;
        }, 350);
      }
      function cleanup() {
        clearInterval(ping);
        clearInterval(poll);
        clearTimeout(timeout);
        window.removeEventListener('message', reply);
        signal.removeEventListener('abort', cleanup);
      }
      window.addEventListener('message', reply);
      signal.addEventListener('abort', cleanup, {once: true});
    } catch (error) {
      if (signal.aborted) return;
      status.textContent = error.message;
      $('open-trace').disabled = false;
    }
  }

  function resize(height) {
    const value = Math.min(4000, Math.max(240, Math.round(height)));
    container.style.setProperty('--viewer-height', value + 'px');
    grip.setAttribute('aria-valuenow', value);
  }

  let drag;
  grip.onpointerdown = event => {
    if (!frame || event.button !== 0) return;
    drag = {y: event.clientY, height: frame.getBoundingClientRect().height};
    grip.setPointerCapture(event.pointerId);
    $('trace').classList.add('resizing');
  };
  grip.onpointermove = event => {
    if (drag) resize(drag.height + event.clientY - drag.y);
  };
  grip.onlostpointercapture = () => {
    drag = null;
    $('trace').classList.remove('resizing');
  };
  grip.onkeydown = event => {
    if (!frame || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    resize(frame.getBoundingClientRect().height + (event.key === 'ArrowDown' ? 32 : -32));
  };
  mode.onchange = updateControls;
  $('open-trace').onclick = open;

  return {
    show(next, platforms, title, context) {
      const nextKey = next ? JSON.stringify([next, title, context]) : '';
      if (nextKey === traceKey) return;
      traceKey = nextKey;
      trace = next;
      label = title;
      close();
      $('trace-actions').hidden = !trace;
      $('trace-source').textContent = trace?.source ?? '';
      $('trace-note').textContent = trace ? [
        context, platforms[trace.platform] ?? trace.platform, trace.date,
        trace.scope === 'full' ? '完整仿真' : '起始窗口', trace.cycles.toLocaleString('zh-CN') + ' cycles'
      ].filter(Boolean).join(' · ') : '该次运行没有归档流水。';
      $('trace-lanes').innerHTML = trace ? Object.entries(trace.lanes ?? {}).map(([unit, [busy, count]]) =>
        `<div title="${escape(busy)} BUSY cycles · ${escape(count)} 个区间">${escape(unit)}
        <strong>${(100 * busy / trace.cycles).toFixed(1)}% BUSY</strong></div>`
      ).join('') : '';
      status.textContent = '';
      if (!trace) return;
      mode.replaceChildren(...(trace.lifecycle ? [new Option('BUSY + pop / retire', 'lifecycle')] : []),
        new Option('仅 BUSY', 'busy'),
        ...(trace.instructions ? [new Option('原始指令时间线', 'instructions')] : []));
      updateControls();
    }
  };
}
