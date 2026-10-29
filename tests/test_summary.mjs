import {prefillP90, prefillSpeed} from '../kanban/static/summary-model.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {overview, toptP90} from '../kanban/static/summary-model.mjs';
test('latest failure remains visible beside historical metrics',()=>{
 const [row]=overview([{id:'old'}],[{recipe_id:'m',status:'SUCCEEDED',result_id:'old',started_at:'2026-10-28T03:00:00+08:00'},{recipe_id:'m',status:'FAILED',started_at:'2026-10-29T03:00:00+08:00'}]);
 assert.equal(row.latest.status,'FAILED');assert.equal(row.run.id,'old');
});
test('timestamp determines latest result, not result identifier order',()=>{
 const [row]=overview([{id:'z'},{id:'a'}],[{recipe_id:'m',status:'SUCCEEDED',result_id:'z',started_at:'2026-10-29T03:00:00+08:00'},{recipe_id:'m',status:'SUCCEEDED',result_id:'a',started_at:'2026-10-29T04:00:00+08:00'}]);assert.equal(row.run.id,'a');
});
test('blocked task has no invented performance result',()=>{
 const [row]=overview([],[{recipe_id:'cann',status:'BLOCKED',started_at:'2026-10-29T03:00:00+08:00'}]);assert.equal(row.run,null);
});

test('TOPT uses per-run token count, excludes first token and takes nearest-rank P90',()=>{
 const samples = [10,20,30,40,50].map((v,i)=>({status:0,decode_ms:v*(i+1),output_callbacks:i+2}));
 samples.push({warmup:true,status:0,decode_ms:9999,output_callbacks:2});
 assert.equal(toptP90({samples}),50);
});
test('TOPT does not invent zero for absent or invalid metrics',()=>{
 for(const samples of [[],[{status:0,decode_ms:null,output_callbacks:128}],[{status:0,decode_ms:1,output_callbacks:1}],[{status:1,decode_ms:10,output_callbacks:128}]]) assert.equal(toptP90({samples}),null);
});

test('combined Prefill reuses measured TTFT, never historical pure evaluation',()=>{
 assert.equal(prefillP90({timing:{ttft_ms:{p90:12},prefill_ms:{p90:10}}}),12);
 assert.equal(prefillP90({timing:{ttft_ms:{p90:0}}}),0);
 for(const v of [undefined,null,NaN,-1,'12']) assert.equal(prefillP90({timing:{ttft_ms:{p90:v}}}),null);
 assert.equal(prefillP90({timing:{prefill_ms:{p90:10}}}),null);
});

test('Prefill rate uses input tokens divided by P90 TTFT in seconds',()=>{
 assert.equal(prefillSpeed({spec:{input_tokens:1024},timing:{ttft_ms:{p90:2000}}}),512);
 for(const duration of [0,-1,null,NaN]) assert.equal(prefillSpeed({spec:{input_tokens:1024},timing:{ttft_ms:{p90:duration}}}),null);
 for(const tokens of [undefined,0,-1,'1024',Infinity]) assert.equal(prefillSpeed({spec:{input_tokens:tokens},timing:{ttft_ms:{p90:2000}}}),null);
});
