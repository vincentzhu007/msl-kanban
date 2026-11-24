const $ = id => document.getElementById(id);
const preview = document.body.hasAttribute('data-preview');

function drawWave() {
  const canvas = $('wave');
  const {width, height} = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const density = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * density;
  canvas.height = height * density;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(density, density);
  const color = ctx.createLinearGradient(0, 0, width, height);
  color.addColorStop(0, '#529e9d');
  color.addColorStop(.52, '#baf8dc');
  color.addColorStop(1, '#64d4c7');
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  for (let row = 0; row < 63; row++) {
    const v = row / 62;
    ctx.beginPath();
    for (let col = 0; col <= 180; col++) {
      const u = col / 180;
      const y = .49 + .27 * Math.sin(u * 6.9 + v * 2.1)
        + (v - .5) * (.5 + .45 * Math.cos(u * 7.2)) - .13 * u;
      if (col === 0) ctx.moveTo(0, y * height);
      else ctx.lineTo(u * width, y * height);
    }
    ctx.globalAlpha = .35 + .45 * Math.sin(Math.PI * v);
    ctx.stroke();
  }
}
new ResizeObserver(drawWave).observe($('wave'));
for (const button of document.querySelectorAll('[data-prompt]')) {
  button.onclick = () => {
    $('prompt').value = button.dataset.prompt;
    $('prompt').focus(); controls();
  };
}
$('prompt').onkeydown = event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault();
    if (!$('send').disabled) $('compose').requestSubmit();
  }
};
let session = '', messages = [], busy = false, from = null;
let activeMode = 'chat', online = false, startingScreen = false;
$('copy').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('sample').textContent);
    $('feedback').textContent = '命令已复制。';
  } catch { $('feedback').textContent = '请选中示例并复制。'; }
};
// Temporary shared tunnel for the two hosted Playground sites.
const sharedEndpoint = 'wss://identifying-choices-will-transit.trycloudflare.com';
const hosted = location.hostname === 'msl-kanban.pages.dev' || location.hostname === 'msl-kanban.vercel.app';
function sharedRequest(path, body) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(sharedEndpoint);
    let controller, settled = false, ended = false;
    const stream = new ReadableStream({
      start(c) { controller = c; },
      cancel() { socket.close(); },
    });
    socket.onopen = () => socket.send(JSON.stringify({path, body, phone:$('phone').value}));
    socket.onmessage = event => {
      try {
        const item = JSON.parse(event.data);
        if (item.status) {
          settled = true;
          resolve(new Response(stream, {status:item.status, headers:{'Content-Type':item.content_type}}));
        } else if (item.data !== undefined) controller.enqueue(new TextEncoder().encode(item.data));
        else if (item.end) { ended = true; controller.close(); socket.close(); }
        else if (item.error) { ended = true; controller.error(Error(item.error)); socket.close(); if (!settled) reject(Error(item.error)); }
      } catch (error) { if (!settled) reject(error); else controller.error(error); socket.close(); }
    };
    socket.onerror = () => { if (!settled) reject(Error('暂时无法连接模型服务。')); };
    socket.onclose = () => { if (!settled) reject(Error('暂时无法连接模型服务。')); else if (!ended) controller.error(Error('模型连接中断。')); };
  });
}
function modelFetch(path, body) {
  if (hosted) return sharedRequest(path, body);
  return fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-Phone-Type':$('phone').value, ...(body ? {'Content-Type':'application/json'} : {})}, body:body ? JSON.stringify(body) : undefined, cache:'no-store', redirect:'error'});
}
async function request(path, body, lease) {
  const headers = {'X-Phone-Type': $('phone').value};
  if (lease) headers['X-Device-Session'] = lease;
  if (body) headers['Content-Type'] = 'application/json';
  const response = hosted && path.startsWith('/v1/') ? await sharedRequest(path, body) : await fetch(path, {
    method: body ? 'POST' : 'GET', headers, body: body && JSON.stringify(body),
    cache: 'no-store', redirect: 'error'
  });
  if (!response.headers.get('content-type')?.includes('application/json'))
    throw Error('当前站点尚未接入 dog 网关。');
  const result = await response.json();
  if (!response.ok) throw Error(result.error?.message || '请求失败，请重新连接。');
  return result;
}
function controls() {
  $('phone').disabled = busy || !!session || startingScreen;
  $('send').disabled = busy || !online || preview || !$('prompt').value.trim();
  $('send').textContent = busy ? '处理中…' : '发送 ↑';
  $('compose-hint').textContent = preview ? '离线预览 · 可编辑提示词，不发送到真机' : !online ? '连接服务后可发送；你可以先编写提示词' : '⌘ / Ctrl + Enter 发送 · Enter 换行';
  $('chat-context').textContent = online ? $('models').selectedOptions[0]?.textContent + ' · 切换模型将开始新对话' : '等待连接 · 草稿可以先写好';
  $('retry').disabled = busy;
  $('copy').disabled = !online || hosted;
  $('clear').disabled = busy || !messages.length;
  $('start').disabled = busy || !online || !!session || preview || hosted;
  $('models').disabled = !online || busy || !!session || startingScreen;
}
$('prompt').addEventListener('input', controls);
function connection(state, title, help) {
  $('connection').closest('.status').dataset.state = state;
  $('connection').textContent = title;
  $('connection-help').textContent = help;
}
function sample() {
  if (hosted) { $('sample').textContent = '网页对话已通过临时共享通路连接真机，HTTP API 暂不对外开放。'; return; }
  const body = {model: $('models').disabled ? '<model-id>' : $('models').value,
    messages: [{role: 'user', content: '你好'}], max_tokens: 1024};
  $('sample').textContent = 'curl ' + (preview ? '"$MSLITE_BASE_URL"' : location.origin) + '/v1/chat/completions \\\n  -H "X-Phone-Type: ' + $('phone').value + '" \\\n  -H "Content-Type: application/json" \\\n  --data-binary @- <<\'JSON\'\n' + JSON.stringify(body, null, 2) + '\nJSON';
}
function reset() {
  messages = [];
  $('history').replaceChildren();
  $('empty').hidden = false;
  controls();
}
function line(role, content) {
  const block = document.createElement('article'), name = document.createElement('strong');
  name.textContent = role;
  block.className = role === '你' ? 'message-user' : 'message-model';
  block.append(name, document.createTextNode(content));
  $('history').append(block);
  const history = $('history');
  history.scrollTop = history.scrollHeight;
}
async function loadModels() {
  $('retry').hidden = true;
  busy = true; controls();
  connection('loading', '正在连接服务', '正在获取所选设备的部署模型。');
  try {
    const {data} = preview
      ? {data: [{id:'Qwen3-4B'}, {id:'Qwen3-0.6B'}]}
      : await request('/v1/models');
    if (!Array.isArray(data) || !data.length) throw Error('服务未登记模型。');
    const scoped = data.some(m => /^(mate80-pro|mate70-pro)\//.test(m.id));
    const prefix = $('phone').value + '/';
    const available = scoped ? data.filter(m => m.id.startsWith(prefix)) : data;
    if (!available.length) throw Error('所选手机尚未登记部署模型。');
    $('models').replaceChildren(...available.map(m => new Option(scoped ? m.id.slice(prefix.length) : m.id, m.id)));
    online = true;
    connection(preview ? 'preview' : 'ready', preview ? '离线预览' : '模型服务已连接', preview ? '示例模型仅供查看界面，不会发送请求或操作手机。' : '已获取部署模型；发送消息时将在真机上加载并运行。');
    reset();
  } catch (e) {
    online = false;
    $('models').replaceChildren(new Option('暂无可用模型', ''));
    connection('offline', '暂未连接模型服务', e.message + ' 可先浏览界面、编写提示词，服务就绪后点击重新连接。');
    $('retry').hidden = false;
  } finally { busy = false; controls(); sample(); }
}
$('retry').onclick = loadModels;
$('phone').onchange = () => {
  online = false;
  reset();
  $('feedback').textContent = '';
  $('screenState').textContent = '';
  $('models').replaceChildren(new Option('正在加载模型…', ''));
  loadModels();
};
// Render buffered text steadily even when the device sends several tokens together.
function createTypewriter(node) {
  const segmenter = typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter(undefined, {granularity: 'grapheme'}) : null;
  let target = '', shown = 0, timer = null, resolveDrain = null;
  const characters = () => segmenter
    ? Array.from(segmenter.segment(target), part => part.segment) : Array.from(target);
  function tick() {
    timer = null;
    const history = $('history');
    const follow = history.scrollHeight - history.scrollTop - history.clientHeight <= 24;
    const parts = characters();
    const remaining = parts.length - shown;
    shown += Math.min(remaining, remaining > 160 ? 3 : remaining > 80 ? 2 : 1);
    node.textContent = parts.slice(0, shown).join('');
    if (follow) history.scrollTop = history.scrollHeight;
    if (shown < parts.length) timer = setTimeout(tick, 25);
    else if (resolveDrain) { resolveDrain(); resolveDrain = null; }
  }
  return {
    append(text) {
      target += text;
      if (timer === null) timer = setTimeout(tick, 25);
    },
    drain() {
      if (timer === null) return Promise.resolve();
      return new Promise(resolve => { resolveDrain = resolve; });
    },
  };
}

$('compose').onsubmit = async event => {
  event.preventDefault();
  const content = $('prompt').value.trim();
  if (!content || busy || !online || preview) return;
  const next = [...messages, {role:'user', content}];
  const model = $('models').value;
  busy = true; controls(); $('feedback').textContent = '';
  $('pending').hidden = false; $('history').setAttribute('aria-busy','true');
  let typewriter;
  try {
    const response = await modelFetch('/v1/chat/completions', {model, messages:next, max_tokens:1024, stream:true});
    if (!response.ok) {
      const error = await response.json();
      throw Error(error.error?.message || '请求失败，请重新连接。');
    }
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body)
      throw Error('服务暂不支持流式输出。');
    $('empty').hidden = true;
    line('你', content);
    line(model, '');
    const answerBlock = $('history').lastElementChild;
    const answerText = document.createTextNode('');
    answerBlock.append(answerText);
    typewriter = createTypewriter(answerText);
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '', answer = '', done = false;
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
      const events = buffer.split('\n\n');
      buffer = events.pop();
      for (const event of events) {
        if (!event.startsWith('data: ')) continue;
        const data = event.slice(6);
        if (data === '[DONE]') { done = true; continue; }
        const item = JSON.parse(data);
        if (item.error) throw Error(item.error.message);
        const text = item.choices?.[0]?.delta?.content || '';
        if (text) {
          $('pending').hidden = true;
          answer += text;
          typewriter.append(text);
        }
      }
      if (chunk.done) break;
    }
    await typewriter.drain();
    if (!done) throw Error('生成中断，请重试。');
    messages = [...next, {role:'assistant', content:answer}];
    if ($('prompt').value.trim() === content) $('prompt').value = '';
    $('feedback').textContent = '';
  } catch (e) {
    if (typewriter) await typewriter.drain();
    $('feedback').textContent = e.message;
    if (!messages.length) $('empty').hidden = false;
  }
  finally { busy = false; $('pending').hidden = true; $('history').setAttribute('aria-busy','false'); controls(); }
};
$('models').onchange = () => {reset(); $('feedback').textContent = ''; sample();};
$('clear').onclick = reset;
function forget() {
  $('standby').hidden = false;
  session = ''; from = null; $('screen').hidden = true; $('screen').removeAttribute('src');
  $('end').hidden = true; controls();
}
async function release() {
  const lease = session;
  forget();
  try { if (lease) await request('/device/end', {}, lease); $('screenState').textContent = ''; }
  catch (e) { $('screenState').textContent = e.message; }
}
async function frames(lease) {
  try {
    while (lease === session) {
      const frame = await request('/device/frame', {}, lease);
      if (lease !== session) return;
      $('screen').src = 'data:image/png;base64,' + frame.png;
      $('standby').hidden = true;
      $('screen').hidden = false; $('screenState').textContent = '';
      await new Promise(resolve => setTimeout(resolve, 900));
    }
  } catch (e) {
    if (lease === session) { await release(); $('screenState').textContent = e.message; }
  }
}
$('start').onclick = async () => {
  startingScreen = true; controls();
  $('start').disabled = true; $('screenState').textContent = '正在打开 App…';
  try {
    session = (await request('/device/start', {})).session;
    if (activeMode !== 'device') { await release(); return; }
    controls(); $('end').hidden = false; frames(session);
  } catch (e) { $('screenState').textContent = e.message; }
  finally { startingScreen = false; controls(); }
};
$('end').onclick = release;
const screen = $('screen');
function point(e) {
  const r = screen.getBoundingClientRect();
  return [Math.max(0, Math.min(screen.naturalWidth-1, Math.floor((e.clientX-r.left)*screen.naturalWidth/r.width))),
          Math.max(0, Math.min(screen.naturalHeight-1, Math.floor((e.clientY-r.top)*screen.naturalHeight/r.height)))];
}
screen.onpointerdown = e => {
  if (!session || !screen.naturalWidth || !e.isPrimary || e.button !== 0) return;
  from = point(e); screen.setPointerCapture(e.pointerId);
};
screen.onpointercancel = () => { from = null; };
screen.onpointerup = async e => {
  if (!from || !session || !e.isPrimary) return;
  const to = point(e), swipe = Math.hypot(to[0]-from[0], to[1]-from[1]) > 12;
  const body = {gesture:swipe?'swipe':'click',points:swipe?[...from,...to]:to};
  from = null;
  try { await request('/device/input', body, session); }
  catch (error) { $('screenState').textContent = error.message; }
};
for (const button of $('modes').querySelectorAll('button')) button.onclick = () => {
  activeMode = button.dataset.mode;
  for (const item of $('modes').querySelectorAll('button')) {
    const selected = item.dataset.mode === activeMode;
    $(item.dataset.mode).hidden = !selected;
    item.setAttribute('aria-pressed', selected);
  }
  if (session && activeMode !== 'device') release();
};
sample();
loadModels();
