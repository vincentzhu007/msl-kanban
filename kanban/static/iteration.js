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
 const collapsed=new Set();
 const renderRows=()=>{
  const query=document.querySelector('#model-search').value.trim().toLowerCase();
  const chip=document.querySelector('#model-chip').value;
  const family=document.querySelector('#model-family').value;
  const shown=modelSupport.filter(m=>(family==='全部架构'||m.family===family)&&`${m.family} ${m.size} ${m.family}-${m.size}`.toLowerCase().includes(query));
  const chips=chip==='全部芯片'?modelChips:[chip];
  document.querySelector('#model-table-head').innerHTML=`<tr><th rowspan="2" scope="col">模型架构 / 参数量</th><th rowspan="2" scope="col">模型链接</th>${chips.map(c=>`<th scope="colgroup" colspan="${modelQuants.length}">${c}</th>`).join('')}</tr><tr>${chips.map(()=>modelQuants.map(q=>`<th scope="col">${q}</th>`).join('')).join('')}</tr>`;
  document.querySelector('#model-rows').innerHTML=shown.length?[...new Set(shown.map(m=>m.family))].map(family=>{
   const items=shown.filter(m=>m.family===family);
   const isCollapsed=collapsed.has(family);
   const heading=`<tr class="model-family-row"><th colspan="${2+chips.length*modelQuants.length}" scope="rowgroup"><button type="button" class="model-family-toggle" data-model-family="${family}" aria-expanded="${!isCollapsed}"><span class="model-family-chevron" aria-hidden="true">${isCollapsed?'▸':'▾'}</span><strong>${family}</strong><span class="model-family-count">${items.length} 个规格</span></button></th></tr>`;
   if(isCollapsed)return heading;
   return heading+items.map(m=>`<tr><th scope="row" class="model-name"><strong>${m.family}</strong><span>${m.size}</span></th><td class="model-link">${m.url?`<a href="${m.url}" target="_blank" rel="noopener noreferrer">查看模型 ↗</a>`:`<span class="model-link-warning">${m.linkNote}</span>`}</td>${chips.map(c=>modelQuants.map(q=>{const listed=!m.listed||(m.listed[c]||[]).includes(q);const yes=(m.supported[c]||[]).includes(q);return `<td class="model-status-cell"><span class="model-state ${!listed?'unlisted':yes?'confirmed':'unknown'}">${!listed?'未列出':yes?'支持':'待确认'}</span></td>`}).join('')).join('')}</tr>`).join('');
  }).join(''):`<tr><td class="blank" colspan="${2+chips.length*modelQuants.length}">没有匹配的模型。</td></tr>`;
  document.querySelector('#model-count').textContent=`${shown.length} 个模型规格`;
 };
 content.innerHTML=`<section class="panel model-panel"><div class="model-panel-head"><div><h2>模型支持清单</h2><p>按模型、芯片和量化方式查看支持情况</p></div><div class="model-legend"><span class="model-state confirmed">支持</span><span>表格标记 YES</span><span class="model-state unknown">待确认</span><span>表格未填写</span><span class="model-state unlisted">未列出</span><span>表格无此组合</span></div></div><div class="model-filters"><label>搜索模型<input id="model-search" type="search" placeholder="搜索架构或参数量" aria-label="搜索模型"></label><label>模型架构<select id="model-family" aria-label="筛选模型架构"><option>全部架构</option>${[...new Set(modelSupport.map(m=>m.family))].map(f=>`<option>${f}</option>`).join('')}</select></label><label>芯片平台<select id="model-chip" aria-label="筛选芯片平台"><option>全部芯片</option>${modelChips.map(c=>`<option>${c}</option>`).join('')}</select></label></div><div class="model-table-wrap" tabindex="0" aria-label="模型支持表，可横向滚动"><table class="model-table"><thead id="model-table-head"></thead><tbody id="model-rows"></tbody></table></div><div class="model-foot"><span id="model-count"></span><span>数据来源：模型支持清单 · 维护者确认</span></div></section><p class="model-disclaimer">表格中的空白状态为待确认；未列出的组合也不能据此判断不支持。</p>`;
 for(const id of ['model-search','model-family','model-chip']) document.querySelector('#'+id).addEventListener(id==='model-search'?'input':'change',renderRows);
 document.querySelector('#model-rows').addEventListener('click',event=>{
  const button=event.target.closest('[data-model-family]');
  if(!button)return;
  const family=button.dataset.modelFamily;
  if(collapsed.has(family))collapsed.delete(family);else collapsed.add(family);
  renderRows();
  [...document.querySelectorAll('[data-model-family]')].find(el=>el.dataset.modelFamily===family)?.focus();
 });
 renderRows();
}
function render(){view=location.hash==='#models'?'models':'overview';document.querySelector('#nav').innerHTML=`<a href="#overview" class="${view==='overview'?'active':''}" ${view==='overview'?'aria-current="page"':''}>特性列表</a><a href="#models" class="${view==='models'?'active':''}" ${view==='models'?'aria-current="page"':''}>模型支持</a>`;document.querySelector('#page-title').textContent=view==='overview'?'特性列表':'模型支持';document.querySelector('#page-subtitle').textContent=view==='overview'?`lite_llm ${version} · ${selected().length} 项${version==='v0.1'?'已完成':'开发中'}`:'按芯片和量化方式查看模型支持';document.querySelector('.version-control').hidden=view==='models';(view==='overview'?overview:models)()}
function showDetail(id){const f=features.find(f=>f.id===Number(id));if(!f)return;const group=groups.find(([,ids])=>ids.includes(f.id))[0];document.querySelector('#detail-content').innerHTML=`<div class="detail-top"><button class="close" aria-label="关闭详情">×</button><div class="eyebrow">${group} / ${f.version}</div><h2 id="detail-title">${f.name}</h2>${status(f.version)}<p>${f.description}</p><a href="${source(f.id)}" target="_blank" rel="noopener">设计 Issue #${f.id} ↗</a></div><div class="detail-body"><h3>关联 PR / Bug</h3><p class="detail-placeholder">尚未关联。后续汇总框架与融合算子两侧的实现和问题。</p><h3>验收与限制</h3><p class="detail-placeholder">详细验收证据与支持配置尚未录入。</p>${[509,541].includes(f.id)?'<div class="detail-note">标题与正文的能力范围待对齐。此项尚未确认为发布阻塞。</div>':''}<h3>关键组合</h3><p class="detail-placeholder">未选定关联组合；独立能力仅在存在交互约束时增加关系。</p></div>`;document.querySelector('#detail').showModal()}
content.addEventListener('click',e=>{const target=e.target.closest('[data-feature]');if(target)showDetail(target.dataset.feature)});
document.querySelector('#detail').setAttribute('aria-labelledby','detail-title');
document.querySelector('#detail').addEventListener('click',e=>{if(e.target.closest('.close')||e.target===e.currentTarget)e.currentTarget.close()});
document.querySelector('#version').addEventListener('change',e=>{version=e.target.value;render()});
window.addEventListener('hashchange',render);
render();
