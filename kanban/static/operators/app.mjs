import {bindAutoRefresh} from '../visible-refresh.mjs';
import {dimensions, seriesKey, measurement, samplePoints, versionKey, versionLabel} from './trends.mjs';
import {createTraceViewer} from './perfetto.mjs';

const $ = id => document.getElementById(id);
const escape = value => String(value ?? '—').replace(/[&<>"']/g,
  character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[character]);
const number = value => Number.isFinite(value) ? value.toLocaleString('zh-CN', {maximumFractionDigits: 3}) : '—';
const latency = value => Number.isFinite(value) ? number(value) + ' µs' : '—';
const source = '/operator-data/';
const url = new URL(location.href);
const viewer = createTraceViewer($, source, escape);
const chart = $('operator-chart');
const tooltip = $('operator-point-tooltip');
let catalog;
let records = [];
let currentSeries = '';
let request = 0;
let axis = 'day';
let selectedItem;
let selectedPoint;
let points = [];
let stateItems = [];
let caseItems = [];

async function json(path) {
  const response = await fetch(source + path, {cache: 'no-cache'});
  if (!response.ok) throw new Error('HTTP ' + response.status + ' · ' + path);
  return response.json();
}

function options(select, entries, wanted) {
  select.replaceChildren(...entries.map(([value, label]) => new Option(label, value)));
  if (entries.some(([value]) => value === wanted)) select.value = wanted;
  select.disabled = !entries.length;
}

function updateQuery() {
  const current = new URL(location.href);
  for (const id of ['operator', 'platform', 'group', 'case', 'date', 'record']) {
    const key = id === 'record' ? 'run' : id;
    if ($(id).value) current.searchParams.set(key, $(id).value);
    else current.searchParams.delete(key);
  }
  history.replaceState(null, '', current);
}

async function refresh(keep = true) {
  const token = ++request;
  const filter = ['operator', 'platform', 'group', 'case', 'date', 'record'];
  const wanted = keep ? Object.fromEntries(filter.map(id => [id, $(id).value ||
    url.searchParams.get(id === 'record' ? 'run' : id)])) : {};
  const previousSeries = currentSeries;
  $('refresh').disabled = true;
  try {
    const next = await json('catalog.json');
    if (token !== request) return;
    const operator = Object.keys(next.operators).includes(wanted.operator) ? wanted.operator : Object.keys(next.operators)[0];
    const available = next.operators[operator] ?? {};
    const platform = Object.hasOwn(next.platforms, wanted.platform) ? wanted.platform :
      Object.keys(available)[0] ?? Object.keys(next.platforms)[0];
    const files = available[platform] ?? [];
    const nextRecords = await Promise.all(files.map(json));
    if (token !== request) return;
    catalog = next;
    records = nextRecords;
    currentSeries = operator + '/' + platform;
    options($('operator'), Object.keys(next.operators).map(name => [name, name]), operator);
    options($('platform'), Object.entries(next.platforms), platform);
    const same = currentSeries === previousSeries || !previousSeries;
    renderFilters(same ? wanted : {});
    $('error').textContent = '';
  } catch (error) {
    if (token === request) $('error').textContent = '加载失败。' + error.message;
  } finally {
    if (token === request) $('refresh').disabled = false;
  }
}

function renderFilters(wanted = {}) {
  const items = records.flatMap((record, order) =>
    record.cases.filter(item => item.group !== 'UT').map(item => ({record, case: item, order})));
  const groups = [...new Set(items.map(item => item.case.group))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const linked = items.find(item => item.record.id === wanted.record && item.case.id === wanted.case);
  options($('group'), groups.map(group => [group, group]), wanted.group || linked?.case.group);
  const cases = items.filter(item => item.case.group === $('group').value);
  options($('case'), [...new Map(cases.map(({case: item}) => [item.id, item.label])).entries()], wanted.case);
  caseItems = cases.filter(item => item.case.id === $('case').value).sort((a, b) =>
    a.record.date.localeCompare(b.record.date) || a.order - b.order);
  const dates = [...new Set(caseItems.map(item => item.record.date))].reverse();
  options($('date'), [['', '全部日期'], ...dates.map(date => [date, date])], wanted.date);
  const platform = catalog.platforms[$('platform').value];
  $('status').textContent = records.length ? platform + ' · ' + records.length + ' 批实测' :
    ($('operator').value ? platform + ' 暂无实测记录' : '暂无算子实测记录');
  selectDate(wanted.record);
}

function selectDate(recordId) {
  stateItems = caseItems.filter(item => !$('date').value || item.record.date === $('date').value);
  for (const id of ['trend', 'detail', 'trace']) $(id).hidden = !stateItems.length;
  selectedItem = stateItems.find(item => item.record.id === recordId) ?? stateItems.at(-1);
  selectedPoint = undefined;
  if (selectedItem) render();
  else {
    options($('record'), []);
    viewer.show(null);
    updateQuery();
  }
}

function render() {
  const metric = Number($('metric').value);
  points = samplePoints(stateItems, axis, metric);
  $('trend-note').textContent = {
    day: '每天采用该规格最后导入的有效实测。点击数据点查看轮次和流水。',
    version: '每个源码版本采用最新日期的实测，同日采用最后导入的记录。',
    run: '按采样时间显示每次热运行。'
  }[axis];
  options($('record'), [...stateItems].reverse().map(({record}) => [
    record.id, record.date + ' · ' + versionLabel(record) + ' · ' + record.id
  ]), selectedItem.record.id);
  drawChart();
  renderDetail();
  updateQuery();
}

function drawChart() {
  tooltip.hidden = true;
  if (!points.length) {
    chart.textContent = '当前规格未采集该指标。';
    return;
  }
  const width = 1080, height = 300, left = 77, right = 1027, top = 24, bottom = 227;
  const low = Math.min(...points.map(point => point.value));
  const high = Math.max(...points.map(point => point.value));
  const padding = Math.max((high - low) * 0.13, high * 0.045);
  const min = Math.max(0, low - padding), max = high + padding;
  const firstDay = Date.parse(points[0].item.record.date);
  const span = Date.parse(points.at(-1).item.record.date) - firstDay;
  const x = (point, index) => points.length === 1 ? (left + right) / 2 :
    left + (right - left) * (axis === 'day' && span ?
      (Date.parse(point.item.record.date) - firstDay) / span : index / (points.length - 1));
  const y = value => bottom - (bottom - top) * (value - min) / (max - min);
  const labelStep = Math.max(1, Math.ceil(points.length / 8));
  const grid = Array.from({length: 5}, (_, index) => {
    const value = min + (max - min) * index / 4;
    const row = y(value);
    return `<line x1="${left}" x2="${right}" y1="${row}" y2="${row}" stroke="#e1eaee"/>
      <text x="${left - 10}" y="${row + 4}" text-anchor="end">${number(value)}</text>`;
  }).join('');
  const marks = points.map((point, index) => {
    const record = point.item.record;
    const active = selectedPoint ? selectedPoint === point : point.item === selectedItem;
    const cx = x(point, index), cy = y(point.value);
    const title = [record.date, versionLabel(record), point.run && ('第 ' + point.run.round + ' 轮 · 热样本 ' + (point.index + 1)),
      latency(point.value), record.device].filter(Boolean).join(' · ');
    const labelX = Math.max(left, Math.min(right, cx));
    const label = index % labelStep === 0 || index === points.length - 1;
    const lines = axis === 'day' ? [record.date] : [
      axis === 'run' ? '#' + (index + 1) + ' · ' + versionLabel(record) : versionLabel(record), record.date
    ];
    return `<g role="button" tabindex="0" class="operator-point" data-index="${index}" aria-label="${escape(title)}">
      <circle cx="${cx}" cy="${cy}" r="13" fill="transparent"/>
      <circle cx="${cx}" cy="${cy}" r="${active ? 6 : 3.5}" fill="${active ? '#168b80' : 'currentColor'}"/>
      </g>${label ? lines.map((line, row) =>
        `<text x="${labelX}" y="${bottom + 22 + row * 18}" text-anchor="middle">${escape(line)}</text>`).join('') : ''}`;
  }).join('');
  const segments = [];
  let previousSeries;
  points.forEach((point, index) => {
    const series = seriesKey(point.item);
    if (series !== previousSeries) segments.push([]);
    segments.at(-1).push(x(point, index) + ',' + y(point.value));
    previousSeries = series;
  });
  const paths = segments.filter(segment => segment.length > 1).map(segment =>
    `<polyline fill="none" stroke="currentColor" stroke-width="2.5" points="${segment.join(' ')}"/>`
  ).join('');
  chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-label="耗时（微秒）">
    ${grid}<text x="${left - 10}" y="12" text-anchor="end">µs</text>${paths}${marks}</svg>`;
}

function renderDetail() {
  const {record, case: item} = selectedItem;
  const sample = selectedPoint?.sample;
  const summary = sample ? '选中热样本' : '本次中位数';
  $('detail-heading').textContent = record.date + ' · ' + versionLabel(record) + ' · ' + item.label;
  const tiles = [
    ['NPU 算子耗时', latency(sample ? sample[1] : measurement(selectedItem, 1)), summary],
    ['RunSync 墙钟耗时', latency(sample ? sample[2] : measurement(selectedItem, 2)), summary],
    ['CAModel', item.trace ? number(item.trace.cycles) : '—',
      item.trace ? (item.trace.scope === 'full' ? '完整仿真 · cycles' : '起始窗口 · cycles') : '暂无同规格流水']
  ];
  $('timing').innerHTML = tiles.map(([name, value, sub]) => (
    `<div class="card"><div class="label">${escape(name)}</div><div class="value">${escape(value)}</div>
    <div class="sub">${escape(sub)}</div></div>`
  )).join('');
  const accuracy = item.accuracy;
  let check = '暂无校验摘要';
  if (accuracy) {
    check = accuracy.summary ?? [
      Number.isFinite(accuracy.max_ulp) && '最大 ' + number(accuracy.max_ulp) + ' ULP',
      Number.isFinite(accuracy.over) && '严格阈值超差 ' + number(accuracy.over) + ' / ' + number(accuracy.elements)
    ].filter(Boolean).join(' · ');
  } else if (item.golden) {
    check = '归档参考 SHA-256 · ' + item.golden;
  }
  const fields = [
    ['规格', dimensions(item.spec) || item.label], ['设备 / 系统', record.device + ' · ' + record.system],
    ['运行模式 / 协议', record.mode + ' · ' + record.protocol], ['算子源码版本', versionKey(record)],
    ['实测日期', record.measured_date],
    ['统计口径', record.statistic === 'hot-samples-median' ? '全部热样本取中位数' : '各轮中位数再取中位数'],
    ['输出校验', check], ['DDK / 运行库', [record.environment?.ddk, record.environment?.runtime].filter(Boolean).join(' · ')]
  ];
  $('metadata').innerHTML = fields.filter(([, value]) => value).map(([label, value]) =>
    `<div>${escape(label)}<b>${escape(value)}</b></div>`).join('');
  $('run-note').textContent = item.note ?? record.note ?? '';
  const count = item.runs.reduce((sum, run) => sum + run.hot.length, 0);
  $('sample-count').textContent = '（' + count + ' 个热样本）';
  $('samples').innerHTML = item.runs.flatMap(run => run.hot.map(row =>
    `<tr${row === sample ? ' aria-current="true"' : ''}>
      <td>第 ${escape(run.round)} 轮 · ${escape(run.warmup)} 次预热</td>
      <td>${escape(row[0])}</td><td>${number(row[1])}</td><td>${number(row[2])}</td>
    </tr>`)).join('');
  viewer.show(item.trace, catalog.platforms, item.label);
}

function pointMarker(target) {
  return target instanceof Element ? target.closest('.operator-point') : null;
}

function showPoint(marker) {
  if (!marker && selectedPoint) {
    marker = chart.querySelector(`[data-index="${points.indexOf(selectedPoint)}"]`);
  }
  if (!marker) {
    tooltip.hidden = true;
    return;
  }
  const point = points[Number(marker.dataset.index)];
  const {record} = point.item;
  const markerRect = marker.getBoundingClientRect();
  const area = chart.getBoundingClientRect();
  const x = (markerRect.left + markerRect.right) / 2 - area.left;
  if (x < 0 || x > area.width) {
    tooltip.hidden = true;
    return;
  }
  const run = point.run;
  const lines = [record.date, latency(point.value)];
  if (run) lines.push(`第 ${run.round} 轮 · 第 ${point.index + 1} 个热样本 · ${point.sample[0]}`);
  tooltip.textContent = lines.join('\n');
  tooltip.hidden = false;
  const gap = 12;
  const left = x + tooltip.offsetWidth + gap <= area.width ? x + gap : x - tooltip.offsetWidth - gap;
  const above = markerRect.top - area.top - tooltip.offsetHeight - gap;
  tooltip.style.left = Math.max(0, left) + 'px';
  tooltip.style.top = (above >= 0 ? above : markerRect.bottom - area.top + gap) + 'px';
}

function selectPoint(event) {
  const marker = pointMarker(event.target);
  if (!marker) return;
  selectedPoint = points[Number(marker.dataset.index)];
  selectedItem = selectedPoint.item;
  $('record').value = selectedItem.record.id;
  drawChart();
  const updatedMarker = chart.querySelector(`[data-index="${marker.dataset.index}"]`);
  updatedMarker.focus({preventScroll: true});
  showPoint(updatedMarker);
  renderDetail();
  updateQuery();
}

$('operator').onchange = $('platform').onchange = () => refresh();
$('group').onchange = () => renderFilters({group: $('group').value});
$('case').onchange = () => renderFilters({group: $('group').value, case: $('case').value});
$('date').onchange = () => selectDate($('record').value);
$('metric').onchange = () => { selectedPoint = undefined; render(); };
$('axes').onclick = event => {
  if (!event.target.dataset.axis) return;
  axis = event.target.dataset.axis;
  for (const button of $('axes').children) button.setAttribute('aria-pressed', button.dataset.axis === axis);
  selectedPoint = undefined;
  render();
};
$('record').onchange = () => {
  selectedItem = stateItems.find(item => item.record.id === $('record').value);
  selectedPoint = undefined;
  drawChart();
  renderDetail();
  updateQuery();
};
chart.onpointerover = event => {
  const marker = pointMarker(event.target);
  if (marker) showPoint(marker);
};
chart.onpointerout = event => {
  if (pointMarker(event.target) && !pointMarker(event.relatedTarget)) showPoint();
};
chart.addEventListener('focusin', event => showPoint(pointMarker(event.target)));
chart.addEventListener('focusout', event => showPoint(pointMarker(event.relatedTarget)));
chart.onscroll = () => showPoint();
window.addEventListener('resize', () => showPoint());
chart.onclick = selectPoint;
chart.onkeydown = event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    selectPoint(event);
  }
};
$('refresh').onclick = () => refresh();
refresh();
bindAutoRefresh(refresh);
