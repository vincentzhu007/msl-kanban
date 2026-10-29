import test from 'node:test';
import assert from 'node:assert/strict';
import {selectRecords} from '../kanban/static/detail-filters.mjs';
const runs = [
  {id:'new',date:'2026-10-29',spec:{model:'Qwen3',soc:'9030'}},
  {id:'cpu',date:'2026-10-29',spec:{model:'Qwen3',soc:'9030'}},
  {id:'old',date:'2026-10-28',spec:{model:'Qwen2.5',soc:'9020'}},
];
test('latest date by default, matching frameworks stay together',()=>{
  const state=selectRecords(runs);
  assert.equal(state.filters.date,'2026-10-29');
  assert.deepEqual(state.candidates.map(x=>x.run.id),['new','cpu']);
});
test('deep link and refresh retain an older record and its categories',()=>{
  const state=selectRecords(runs,{date:'2026-10-29'},'old');
  assert.deepEqual(state.filters,{date:'2026-10-28',model:'Qwen2.5',soc:'9020'});
  assert.equal(state.index,2);
  assert.equal(selectRecords(runs,{},'cpu').index,1);
});
test('date change resets unavailable downstream selections',()=>{
  const state=selectRecords(runs,{date:'2026-10-28',model:'Qwen3',soc:'9030'});
  assert.equal(state.filters.model,'Qwen2.5');
  assert.equal(state.filters.soc,'9020');
});
test('missing record falls back; empty results clear selection',()=>{
  assert.equal(selectRecords(runs,{},'removed').index,0);
  assert.equal(selectRecords([]).index,undefined);
  assert.deepEqual(selectRecords([]).candidates,[]);
});
