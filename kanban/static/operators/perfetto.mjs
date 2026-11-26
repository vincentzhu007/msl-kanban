const VIEWER_ORIGIN = 'https://ui.perfetto.dev';
const VIEWER_URL = VIEWER_ORIGIN + '/#!/?mode=embedded';

async function readTrace(url, signal) {
  const response = await fetch(url, {signal});
  if (!response.ok) throw new Error('流水文件请求失败（HTTP ' + response.status + '）');
  const buffer = await response.arrayBuffer();
  const data = new Uint8Array(buffer);
  if (data[0] !== 31 || data[1] !== 139) return buffer;
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).arrayBuffer();
}

function waitForViewer(viewer, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const ping = setInterval(() => {
      if (viewer.closed) {
        cleanup();
        reject(new Error('Perfetto 查看器已关闭或连接已中断。'));
        return;
      }
      viewer.postMessage('PING', VIEWER_ORIGIN);
    }, 150);
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error('Perfetto 加载超时，请检查能否访问 ui.perfetto.dev，或下载流水文件。'));
    }, 90000);
    function reply(event) {
      if (event.origin !== VIEWER_ORIGIN || event.source !== viewer || event.data !== 'PONG') return;
      cleanup();
      resolve();
    }
    function abort() {
      cleanup();
      reject(signal.reason);
    }
    function cleanup() {
      clearInterval(ping);
      clearTimeout(timeout);
      window.removeEventListener('message', reply);
      signal?.removeEventListener('abort', abort);
    }
    window.addEventListener('message', reply);
    signal?.addEventListener('abort', abort, {once: true});
  });
}

export function createTraceViewer($, dataRoot, escape) {
  const container = $('viewer');
  const grip = $('viewer-grip');
  const status = $('trace-status');
  const mode = $('trace-mode');
  const openButton = $('open-trace');
  let trace, label, traceKey, pending, frame;
  let statusVersion = 0;

  function close() {
    statusVersion++;
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
    openButton.disabled = false;
    status.textContent = mode.value === 'lifecycle' ? 'pop 和 retire 轨道位于对应流水的 BUSY 下方。' : '';
  }

  async function open(inNewTab) {
    let viewer;
    let signal;
    if (inNewTab) {
      viewer = window.open(VIEWER_ORIGIN + '/', '_blank');
      if (!viewer) {
        statusVersion++;
        status.textContent = '浏览器拦截了新标签页，请允许本站弹出窗口后重试。';
        return;
      }
    } else {
      close();
      pending = new AbortController();
      signal = pending.signal;
      openButton.disabled = true;
    }
    const version = ++statusVersion;
    const title = label + ' · Perfetto 流水';
    status.textContent = inNewTab ? '正在向新标签页发送流水…' : '正在载入 Perfetto…';
    try {
      const buffer = await readTrace(dataRoot + selectedFile(), signal);
      signal?.throwIfAborted();
      if (!inNewTab) {
        const iframe = document.createElement('iframe');
        iframe.title = title;
        iframe.src = VIEWER_URL;
        iframe.referrerPolicy = 'no-referrer';
        iframe.allowFullscreen = true;
        frame = iframe;
        container.replaceChildren(iframe);
        grip.hidden = false;
        viewer = iframe.contentWindow;
      }
      await waitForViewer(viewer, signal);
      signal?.throwIfAborted();
      viewer.postMessage({perfetto: {buffer, title, fileName: 'trace.json'}}, VIEWER_ORIGIN, [buffer]);
      if (version === statusVersion) {
        const location = inNewTab ? '新标签页' : '查看器';
        status.textContent = `流水已发送给 Perfetto。若出现信任提示，请在${location}内确认。`;
      }
    } catch (error) {
      if (!signal?.aborted && version === statusVersion) status.textContent = error.message;
    } finally {
      if (signal && !signal.aborted) {
        pending = null;
        openButton.disabled = false;
      }
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
  openButton.onclick = () => open(false);
  $('open-trace-tab').onclick = () => open(true);

  return {
    show(next, platforms, title) {
      const nextKey = next ? JSON.stringify([next, title]) : '';
      if (nextKey === traceKey) return;
      traceKey = nextKey;
      trace = next;
      label = title;
      close();
      $('trace-actions').hidden = !trace;
      $('trace-source').textContent = trace?.source ?? '';
      $('trace-note').textContent = trace ? [
        platforms[trace.platform] ?? trace.platform, trace.date,
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
