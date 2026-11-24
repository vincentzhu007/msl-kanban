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
async function request(path, body, lease) {
  const headers = {'X-Phone-Type': $('phone').value};
  if (lease) headers['X-Device-Session'] = lease;
  if (body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
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
  $('copy').disabled = !online;
  $('clear').disabled = busy || !messages.length;
  $('start').disabled = busy || !online || !!session || preview;
  $('models').disabled = !online || busy || !!session || startingScreen;
}
$('prompt').addEventListener('input', controls);
function connection(state, title, help) {
  $('connection').closest('.status').dataset.state = state;
  $('connection').textContent = title;
  $('connection-help').textContent = help;
}
function sample() {
  const body = {model: $('models').disabled ? '<model-id>' : $('models').value,
    messages: [{role: 'user', content: '你好'}], max_tokens: 128};
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
  block.scrollIntoView({block:'nearest'});
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
    $('models').replaceChildren(...data.map(m => new Option(m.id, m.id)));
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
$('compose').onsubmit = async event => {
  event.preventDefault();
  const content = $('prompt').value.trim();
  if (!content || busy || !online || preview) return;
  const next = [...messages, {role:'user', content}];
  const model = $('models').value;
  busy = true; controls(); $('feedback').textContent = '';
  $('pending').hidden = false; $('history').setAttribute('aria-busy','true');
  try {
    const result = await request('/v1/chat/completions', {model, messages:next,max_tokens:128});
    const answer = result.choices[0].message;
    if (!messages.length) $('history').replaceChildren();
    messages = [...next, answer];
    $('empty').hidden = true;
    line('你', content); line(model, answer.content);
    if ($('prompt').value.trim() === content) $('prompt').value = '';
    $('feedback').textContent = '';
  } catch (e) { $('feedback').textContent = e.message; }
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
