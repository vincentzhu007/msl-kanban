const source = id => `https://gitcode.com/mindspore/mindspore-lite/issues/${id}`;
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
function models(){
 const configs=modelConfigs.filter(m=>version==='v0.2'||m.since==='v0.1');
 const models=[];
 for(const config of configs){
  let model=models.find(m=>m.name===config.name&&m.category===config.category);
  if(!model){model={name:config.name,category:config.category,configs:[]};models.push(model)}
  model.configs.push(config);
 }
 const configLines=(model,render)=>model.configs.map(config=>`<div class="model-config-line">${render(config)}</div>`).join('');
 content.innerHTML=`<section class="panel"><div class="panel-head"><h2>模型清单</h2><small>按模型类别分组</small></div><div class="table-scroll"><table><thead><tr><th>模型名称</th><th>芯片平台</th><th>量化方式</th><th>配置来源</th></tr></thead><tbody>${[...new Set(configs.map(m=>m.category))].map(category=>`<tr class="group-heading"><th colspan="4">${category}</th></tr>`+models.filter(m=>m.category===category).map(m=>`<tr><td>${m.name}</td><td>${[...new Set(m.configs.flatMap(c=>c.chip.split("、")))].map(chip=>`<div class="model-config-line">${chip}</div>`).join('')}</td><td>${configLines(m,c=>`<span title="支持平台：${c.chip}">${c.quant}</span>`)}</td><td>${configLines(m,c=>`<a href="${source(c.issue)}" target="_blank" rel="noopener">#${c.issue} ↗</a>`)}</td></tr>`).join('')).join('')}</tbody></table></div><p class="support-note">配置按关联设计整理，支持结论待维护者确认；v0.2 同时保留 v0.1 已有配置。LoRA、采样等能力在特性列表中跟踪。</p></section>`
}
function render(){view=location.hash==='#models'?'models':'overview';document.querySelector('#nav').innerHTML=`<a href="#overview" class="${view==='overview'?'active':''}" ${view==='overview'?'aria-current="page"':''}>特性列表</a><a href="#models" class="${view==='models'?'active':''}" ${view==='models'?'aria-current="page"':''}>模型支持</a>`;document.querySelector('#page-title').textContent=view==='overview'?'特性列表':'模型支持';document.querySelector('#page-subtitle').textContent=view==='overview'?`lite_llm ${version} · ${selected().length} 项${version==='v0.1'?'已完成':'开发中'}`:`lite_llm ${version} · 模型与部署配置`;(view==='overview'?overview:models)()}
function showDetail(id){const f=features.find(f=>f.id===Number(id));if(!f)return;const group=groups.find(([,ids])=>ids.includes(f.id))[0];document.querySelector('#detail-content').innerHTML=`<div class="detail-top"><button class="close" aria-label="关闭详情">×</button><div class="eyebrow">${group} / ${f.version}</div><h2 id="detail-title">${f.name}</h2>${status(f.version)}<p>${f.description}</p><a href="${source(f.id)}" target="_blank" rel="noopener">设计 Issue #${f.id} ↗</a></div><div class="detail-body"><h3>关联 PR / Bug</h3><p class="detail-placeholder">尚未关联。后续汇总框架与融合算子两侧的实现和问题。</p><h3>验收与限制</h3><p class="detail-placeholder">详细验收证据与支持配置尚未录入。</p>${[509,541].includes(f.id)?'<div class="detail-note">标题与正文的能力范围待对齐。此项尚未确认为发布阻塞。</div>':''}<h3>关键组合</h3><p class="detail-placeholder">未选定关联组合；独立能力仅在存在交互约束时增加关系。</p></div>`;document.querySelector('#detail').showModal()}
content.addEventListener('click',e=>{const target=e.target.closest('[data-feature]');if(target)showDetail(target.dataset.feature)});
document.querySelector('#detail').setAttribute('aria-labelledby','detail-title');
document.querySelector('#detail').addEventListener('click',e=>{if(e.target.closest('.close')||e.target===e.currentTarget)e.currentTarget.close()});
document.querySelector('#version').addEventListener('change',e=>{version=e.target.value;render()});
window.addEventListener('hashchange',render);
render();
