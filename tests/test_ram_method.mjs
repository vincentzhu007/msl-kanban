import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {baselineLabel, compareRamLines, netPssKind, ramComparable, RAM_MISMATCH} from '../kanban/static/ram-method.mjs';
import {visibleAuditText} from '../kanban/static/audit-view.mjs';
import {overview} from '../kanban/static/summary-model.mjs';
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
test('real warning shape is collected-but-unstable in the comparison cell',()=>{
 const memory={
  baseline_pss_kib:{median:89836,min:76680,max:89902,samples:5,accepted:false,sample_kib:[76680,85528,89836,89838,89902],range_kib:13222,stability_limit_kib:8983.6},
  total_pss_kib:{sampled_peak:417842,inference_sampled_peak:417842,stable_median:417415.5,stable_min:417196,stable_max:417451},
  graph_kib:{stable_median:265796},
  quality:{warnings:[{code:'pss_baseline_unstable',net_pss_kib:'not_calculated',observed_method:'pre-model-create-pss-v1'}]},
 };
 assert.equal('net_pss_kib' in memory,false);
 assert.equal('ram_method' in memory,false);
 assert.equal(netPssKind(memory),'not_calculated');
 assert.deepEqual(compareRamLines(memory),['— MiB','已采集但不稳定','净 PSS 未计算']);
 assert.equal(compareRamLines(memory).includes('未采集底噪'),false);
 assert.deepEqual(compareRamLines({}),['— MiB','未采集底噪']);
 const app=readFileSync(new URL('../kanban/static/app.js',import.meta.url),'utf8');
 assert.match(app,/compareRamLines\(x\.memory\)/);
 assert.equal(app.includes('baselineLabel(x.memory?.ram_method)'),false);
});
test('offline audit stays outside the daily failure count',()=>{
 const job=JSON.parse(readFileSync(new URL('../kanban/jobs/daily-20261119-qwen25-05b-msl-q30-kirin9020-44432299518-1.json',import.meta.url),'utf8'));
 const record=JSON.parse(readFileSync(new URL('../kanban/audits/offline-review-20261119-q30.record.json',import.meta.url),'utf8'));
 const row=overview([], [job]);
 assert.equal(row[0].latest.status,'FAILED');
 assert.equal(row[0].run,null);
 assert.equal(record.record_kind,'independent_offline_revalidation');
 assert.equal(record.new_device_run,false);
 const text=visibleAuditText(record).join('\n');
 assert.match(text,/已采集但不稳定/);
 assert.match(text,/净 PSS 未计算/);
 assert.match(text,/44432299518/);
 assert.equal(text.includes('未采集底噪'),false);
 assert.equal(text.includes('SUCCEEDED'),false);
});
test('detail page uses method-aware labels, no hard-coded scope',()=>{
 const app=readFileSync(new URL('../kanban/static/app.js',import.meta.url),'utf8');
 assert.ok(!app.includes('扣除创建模型前底噪'));
 assert.ok(app.includes('baselineLabel(mem.ram_method)'));
 assert.ok(app.includes('ramComparable(x,r)'));
});
