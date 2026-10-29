import test from 'node:test';
import assert from 'node:assert/strict';
import {overview} from '../kanban/static/summary-model.mjs';
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
