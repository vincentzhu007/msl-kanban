const source = id => `https://gitcode.com/mindspore/mindspore-lite/issues/${id}`;
const features = [
  [415,'运行时 API','基础框架','v0.1','模型生命周期、文本生成、流式输出与运行时调用契约。'],
  [416,'模型导出工具','基础框架','v0.1','从源模型到端侧模型资源包的导出与转换流程。'],
  [386,'模型资源打包','模型资产','v0.1','统一交付模型、词表、权重与配置资源。'],
  [393,'Qwen Tokenizer','基础框架','v0.1','文本与 Token 转换，以及配套文本处理能力。'],
  [513,'MSL 模型 Schema','模型资产','v0.2','明确模型资源包的结构与约束，衔接导出工具和运行时。'],
  [514,'ModelZoo','模型资产','v0.2','建立模型资产与使用入口，集中呈现适用配置和部署方式。'],
  [465,'多种采样策略','生成与加速','v0.2','跟踪生成采样策略及参数边界；详细验收范围待维护者确认。'],
  [408,'Prefix Cache','生成与加速','v0.2','复用共享 Prompt 前缀的 KV Cache，减少重复 Prefill 计算。'],
  [410,'DFlash 投机解码','生成与加速','v0.2','跟踪 Draft / Target 配套导出、推理流程与精度性能验证。'],
  [512,'4bit 离线量化','量化','v0.2','跟踪离线量化工具与运行时、融合算子的配套交付。'],
  [561,'Q3_0 量化导出与推理','量化','v0.2','Qwen2.5-0.5B Q3_0 导出与推理，以及源码融合算子配套。'],
  [507,'Qwen3-4B','模型支持','v0.2','Qwen3 系列模型端到端推理；设计中重点转测模型为 Qwen3-4B。'],
  [510,'MiniCPM5-1B / 2B','模型支持','v0.2','跟踪 MiniCPM5 模型导出、部署与生成验证。'],
  [541,'Qwen3.5-35A3B','模型支持','v0.2','模型推理能力的交付目标；具体范围需与设计正文对齐。'],
  [509,'Qwen3-VL-Embedding-2B','多模态','v0.2','多模态模型支持目标；具体范围需与设计正文对齐。'],
  [394,'Qwen2.5-0.5B LoRA','LoRA','v0.2','跟踪 LoRA 适配、模型部署与推理能力。'],
  [450,'QNN HTP 后端','后端扩展','v0.2','QNN 整图转换、融合算子接入与 HTP 推理后端。'],
  [511,'性能 TRACE','性能分析','v0.2','关联 CPU 阶段与 NPU Kernel 时间线，支持请求指标与热点分析。']
].map(([id,name,category,version,description])=>({id,name,category,version,description}));
const groups = [
  ['量化与推理加速',[512,561,408,410]],
  ['生成控制',[465]],
  ['工具与观测',[513,514,511]],
  ['模型支持',[507,510,541,509]],
  ['扩展能力',[394,450]],
  ['基础框架',[415,416,386,393]]
];
// Only maintainer-selected combinations belong here; do not generate a Cartesian product.
const combinations = [];
let version='v0.2', view='overview';
const content=document.querySelector('#content');
const selected=()=>features.filter(f=>f.version===version);
const status=v=>`<span class="status ${v==='v0.1'?'done':'dev'}">${v==='v0.1'?'已完成':'开发中'}</span>`;
function groupedRows(query='',category='全部分类'){
  const fs=selected().filter(f=>(f.name+' '+f.id).toLowerCase().includes(query.toLowerCase()));
  let total=0;
  const html=groups.filter(([name])=>category==='全部分类'||name===category).map(([name,ids])=>{
    const items=fs.filter(f=>ids.includes(f.id));total+=items.length;
    if(!items.length)return '';
    return `<tr class="group-heading"><th colspan="4">${name}<span class="count">${items.length}</span></th></tr>`+items.map(f=>`<tr><td><button class="feature-button" data-feature="${f.id}">${f.name}</button><a class="issue-inline" href="${source(f.id)}" target="_blank" rel="noopener">#${f.id} ↗</a></td><td>${status(f.version)}</td><td class="subtle">—</td><td>${[509,541].includes(f.id)?'<span class="scope-note">设计范围待对齐</span>':'<span class="subtle">—</span>'}</td></tr>`).join('');
  }).join('');
  return {html:html||'<tr><td colspan="4" class="blank">没有匹配的特性。</td></tr>',total};
}
function overview(){
 const result=groupedRows();
 content.innerHTML=`<section class="attention"><div><strong>需要关注</strong><small>阻塞清单尚未确认</small></div>${version==='v0.2'?`<p><button data-feature="509">#509 多模态范围</button><span>、</span><button data-feature="541">#541 模型与量化范围</button><span>：标题与正文待对齐，尚未判定为发布阻塞。</span></p>`:'<p>本版本 4 项特性已由维护者确认完成。</p>'}</section>
 <section class="panel"><div class="table-tools"><h2>分类特性清单</h2><div class="filters"><input id="search" type="search" aria-label="搜索特性" placeholder="搜索特性或 Issue…"><select id="category" aria-label="筛选分类"><option>全部分类</option>${groups.filter(([,ids])=>selected().some(f=>ids.includes(f.id))).map(([name])=>`<option>${name}</option>`).join('')}</select></div></div><div class="table-scroll"><table><thead><tr><th>特性 / 设计</th><th>状态</th><th>关联 PR / Bug</th><th>组合 / 限制</th></tr></thead><tbody id="feature-rows">${result.html}</tbody></table></div><p class="table-foot"><span id="result-count">${result.total} 项特性</span><span>— 尚未录入；点击特性查看详情。</span></p></section>
 <section class="panel" id="combinations"><div class="panel-head"><h2>关键组合验证</h2><small>由维护者选择验证范围</small></div><div class="combination-empty">尚未选定关键组合。只记录需要联合验证的特性及适用配置；采样、观测等能力独立分类，有交互限制时再关联。</div><div class="combination-columns"><span>特性组合</span><span>适用模型 / 芯片 / 版本</span><span>结论与证据</span></div></section>`;
 const update=()=>{const result=groupedRows(document.querySelector('#search').value,document.querySelector('#category').value);document.querySelector('#feature-rows').innerHTML=result.html;document.querySelector('#result-count').textContent=result.total+' 项特性'};
 document.querySelector('#search').addEventListener('input',update);document.querySelector('#category').addEventListener('change',update);
}
const modelConfigs = [
  {name:'Qwen2.5-0.5B',category:'文本生成 · Dense',chip:'Kirin 9020',quant:'Q4_0',since:'v0.1',issue:416},
  {name:'Qwen2.5-0.5B',category:'文本生成 · Dense',chip:'Kirin 9020、Kirin 9030',quant:'Q3_0',since:'v0.2',issue:561},
  {name:'Qwen3-4B',category:'文本生成 · Dense',chip:'Kirin 9030',quant:'S16S4',since:'v0.2',issue:507},
  {name:'MiniCPM5-1B',category:'文本生成 · Dense',chip:'待确认',quant:'待确认',since:'v0.2',issue:510},
  {name:'MiniCPM5-2B',category:'文本生成 · Dense',chip:'待确认',quant:'待确认',since:'v0.2',issue:510},
  {name:'Qwen3.5-35B-A3B',category:'文本生成 · MoE',chip:'待确认',quant:'待确认',since:'v0.2',issue:541},
  {name:'Qwen3-VL-Embedding-2B',category:'多模态 · Embedding',chip:'待确认',quant:'待确认',since:'v0.2',issue:509}
];
function models(){
 const configs=modelConfigs.filter(m=>version==='v0.2'||m.since==='v0.1');
 content.innerHTML=`<section class="panel"><div class="panel-head"><h2>模型清单</h2><small>按模型类别分组</small></div><div class="table-scroll"><table><thead><tr><th>模型名称</th><th>芯片平台</th><th>量化方式</th><th>配置来源</th></tr></thead><tbody>${[...new Set(configs.map(m=>m.category))].map(category=>`<tr class="group-heading"><th colspan="4">${category}</th></tr>`+configs.filter(m=>m.category===category).map(m=>`<tr><td>${m.name}</td><td>${m.chip}</td><td>${m.quant}</td><td><a href="${source(m.issue)}" target="_blank" rel="noopener">#${m.issue} ↗</a></td></tr>`).join('')).join('')}</tbody></table></div><p class="support-note">配置按关联设计整理，支持结论待维护者确认；v0.2 同时保留 v0.1 已有配置。LoRA、采样等能力在特性列表中跟踪。</p></section>`
}
function render(){view=location.hash==='#models'?'models':'overview';document.querySelector('#nav').innerHTML=`<a href="#overview" class="${view==='overview'?'active':''}" ${view==='overview'?'aria-current="page"':''}>特性列表</a><a href="#models" class="${view==='models'?'active':''}" ${view==='models'?'aria-current="page"':''}>模型支持</a>`;document.querySelector('#page-title').textContent=view==='overview'?'特性列表':'模型支持';document.querySelector('#page-subtitle').textContent=view==='overview'?`lite_llm ${version} · ${selected().length} 项${version==='v0.1'?'已完成':'开发中'}`:`lite_llm ${version} · 模型与部署配置`;document.querySelector('.eyebrow').textContent='LITE LLM';(view==='overview'?overview:models)()}
function showDetail(id){const f=features.find(f=>f.id===Number(id));if(!f)return;const group=groups.find(([,ids])=>ids.includes(f.id))[0];document.querySelector('#detail-content').innerHTML=`<div class="detail-top"><button class="close" aria-label="关闭详情">×</button><div class="eyebrow">${group} / ${f.version}</div><h2 id="detail-title">${f.name}</h2>${status(f.version)}<p>${f.description}</p><a href="${source(f.id)}" target="_blank" rel="noopener">设计 Issue #${f.id} ↗</a></div><div class="detail-body"><h3>关联 PR / Bug</h3><p class="detail-placeholder">尚未关联。后续汇总框架与融合算子两侧的实现和问题。</p><h3>验收与限制</h3><p class="detail-placeholder">详细验收证据与支持配置尚未录入。</p>${[509,541].includes(f.id)?'<div class="detail-note">标题与正文的能力范围待对齐。此项尚未确认为发布阻塞。</div>':''}<h3>关键组合</h3><p class="detail-placeholder">未选定关联组合；独立能力仅在存在交互约束时增加关系。</p></div>`;document.querySelector('#detail').showModal()}
content.addEventListener('click',e=>{const target=e.target.closest('[data-feature]');if(target)showDetail(target.dataset.feature)});
document.querySelector('#detail').setAttribute('aria-labelledby','detail-title');
document.querySelector('#detail').addEventListener('click',e=>{if(e.target.closest('.close')||e.target===e.currentTarget)e.currentTarget.close()});
document.querySelector('#version').addEventListener('change',e=>{version=e.target.value;render()});
window.addEventListener('hashchange',render);
render();
