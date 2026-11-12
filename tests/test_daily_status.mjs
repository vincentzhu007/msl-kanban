import test from 'node:test';
import assert from 'node:assert/strict';
import {selectDaily,dailyTaskSummary} from '../kanban/static/summary-model.mjs';
test('summary counts latest attempt per recipe, all statuses and selected archive date',()=>{
 const job=(recipe,status,hour,date='20261112')=>({recipe_id:recipe,status,date,started_at:`2026-11-12T${hour}:00:00+08:00`});
 const jobs=[job('a','FAILED','03'),job('a','SUCCEEDED','04'),job('b','BLOCKED','03'),job('c','RUNNING','03'),job('d','SKIPPED','03'),job('e','NO_BUILD','03'),job('f','CANCELLED','03'),job('g','FAILED','03'),job('h','NEW_STATUS','03'),job('old','SUCCEEDED','03','20261111')];
 const summary=dailyTaskSummary(selectDaily([],jobs,'2026-11-12').jobs);
 assert.equal(summary.total,8);assert.equal(summary.attempts,9);
 assert.deepEqual(summary.counts,{SUCCEEDED:1,FAILED:1,BLOCKED:1,RUNNING:1,SKIPPED:1,NO_BUILD:1,CANCELLED:1,OTHER:1});
 assert.equal(dailyTaskSummary([]).total,0);
 assert.equal(Object.values(dailyTaskSummary([]).counts).reduce((a,b)=>a+b),0);
});

test('PC-only CANN Kit archives do not enter mobile counts or date selection',async()=>{
 const {mobileKanbanRecords}=await import('../kanban/static/summary-model.mjs');
 const jobs=[{id:'daily-cann-kit-llm-kirin9020',recipe_id:'cann-kit-llm-kirin9020',date:'20261113',status:'BLOCKED'}, {recipe_id:'qwen3-4b',date:'20261112',status:'SUCCEEDED'}];
 const state=selectDaily([],mobileKanbanRecords(jobs));
 assert.equal(state.date,'2026-11-12');
 assert.equal(dailyTaskSummary(state.jobs).total,1);
 assert.equal(dailyTaskSummary(state.jobs).counts.BLOCKED,0);
 assert.equal(mobileKanbanRecords([{id:'daily-cann-kit-test'}]).length,0);
});
