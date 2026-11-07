import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {baselineLabel, ramComparable, RAM_MISMATCH} from '../kanban/static/ram-method.mjs';
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
test('detail page uses method-aware labels, no hard-coded scope',()=>{
 const app=readFileSync(new URL('../kanban/static/app.js',import.meta.url),'utf8');
 assert.ok(!app.includes('扣除创建模型前底噪'));
 assert.ok(app.includes('baselineLabel(mem.ram_method)'));
 assert.ok(app.includes('ramComparable(x,r)'));
});
