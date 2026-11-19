import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {baselineLabel, netPssKind, ramComparable, RAM_MISMATCH} from '../kanban/static/ram-method.mjs';
const rec=m=>({memory:m?{ram_method:m,net_pss_kib:{stable_median:1}}:{}});
test('baseline label follows ram_method',()=>{
 assert.equal(baselineLabel('pre-runtime-pss-v1'),'扣除加载运行库前底噪');
 assert.equal(baselineLabel('pre-model-create-pss-v1'),'扣除首次创建模型前底噪');
 assert.match(baselineLabel('x-v9'),/未知.*x-v9/);
 assert.equal(baselineLabel(undefined),'未采集底噪');
});
test('different RAM methods are flagged as not comparable',()=>{
 assert.equal(ramComparable(rec('pre-runtime-pss-v1'),rec('pre-model-create-pss-v1')),false);
 assert.equal(ramComparable(rec('pre-model-create-pss-v1'),rec('pre-model-create-pss-v1')),true);
 assert.match(RAM_MISMATCH,/不直接可比/);
});
test('unstable baseline estimate is labeled and missing net stays uncollected',()=>{
 assert.equal(netPssKind({quality:{warnings:[{code:'pss_baseline_unstable'}]},net_pss_kib:{stable_median:1}}),'not_calculated');
 assert.equal(netPssKind({net_pss_kib:{stable_median:1}}),'net');
 assert.equal(netPssKind({total_pss_kib:{stable_median:0}}),'uncollected');
 assert.equal(netPssKind(undefined),'uncollected');
});
test('summary and detail keep the unstable estimate visible',()=>{
 const summary=readFileSync(new URL('../kanban/static/summary.js',import.meta.url),'utf8');
 const app=readFileSync(new URL('../kanban/static/app.js',import.meta.url),'utf8');
 const page=readFileSync(new URL('../kanban/static/index.html',import.meta.url),'utf8');
 assert.match(summary,/netPssKind\(r\.memory\)/);
 assert.match(summary,/kind === 'not_calculated'/);
 assert.match(summary,/净 PSS 未计算/);
 assert.match(app,/netPssKind\(mem\)/);
 assert.match(app,/净 PSS 未计算/);
 assert.match(page,/净 PSS 不计算/);
});
test('detail page uses method-aware labels, no hard-coded scope',()=>{
 const app=readFileSync(new URL('../kanban/static/app.js',import.meta.url),'utf8');
 assert.ok(!app.includes('扣除创建模型前底噪'));
 assert.ok(app.includes('baselineLabel(mem.ram_method)'));
 assert.ok(app.includes('ramComparable(x,r)'));
});
