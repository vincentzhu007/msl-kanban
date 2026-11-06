import test from 'node:test';
import assert from 'node:assert/strict';
import {seriesKey,trendPoints,weekStart,improvement} from '../kanban/static/trends.mjs';
const run=(id,value,n=10)=>({id,recipe_id:'m',spec:{model:'q',soc:'k',consecutive_runs:n},timing:{decode_tps:{p90:value}}});
const job=(date,id,status='SUCCEEDED',hour='03')=>({date,started_at:`${date}T${hour}:00:00+08:00`,result_id:id,status});
test('daily takes latest successful retry, excludes reused and failed runs, leaves gaps',()=>{
 const runs=[run('a',10),run('b',20),run('c',99)];
 const jobs=[job('2026-11-02','a'),job('2026-11-02','b','SUCCEEDED','04'),job('2026-11-02','c','FAILED','05'),job('2026-11-03','b','SKIPPED')];
 assert.deepEqual(trendPoints(runs,jobs,seriesKey(runs[0]),'2026-11-04','day',3).map(p=>p.value),[20,null,null]);
});
test('weekly aggregates daily values equally and separates Monday boundaries',()=>{
 const runs=[run('a',10),run('b',30),run('c',80)];
 const jobs=[job('2026-11-01','a'),job('2026-11-02','b'),job('2026-11-03','c')];
 const p=trendPoints(runs,jobs,seriesKey(runs[0]),'2026-11-03','week',3);
 assert.deepEqual(p.map(x=>[x.date,x.value,x.values.length]),[['2026-10-26',10,1],['2026-11-02',55,2]]);
 assert.equal(weekStart('2027-01-01'),'2026-12-28');
});
test('sample counts share a series while other protocol changes remain separate',()=>{
 assert.equal(seriesKey(run('a',10,5)),seriesKey(run('b',10,10)));
 const different=run('c',10); different.spec.input_tokens=2048;
 assert.notEqual(seriesKey(run('a',10)),seriesKey(different));
 assert.equal(improvement(100,120,true),19.999999999999996);
 assert.ok(Math.abs(improvement(100,80,false)-20)<1e-8);
 assert.equal(improvement(0,10,true),null);
});

import {automaticBaseline} from '../kanban/static/trends.mjs';
const days=values=>values.map((value,i)=>({date:`2026-11-${String(i+1).padStart(2,'0')}`,value}));
test('baseline confirmation is causal; sustained gains promote, regression never lowers baseline',()=>{
 const result=automaticBaseline(days([100,102,98,110,112,114,90,89,88]),true);
 assert.equal(result.states.get('2026-11-02').baseline,null);
 assert.equal(result.states.get('2026-11-03').baseline.value,100);
 assert.equal(result.states.get('2026-11-05').baseline.value,100);
 assert.equal(result.states.get('2026-11-06').baseline.value,112);
 assert.equal(result.states.get('2026-11-09').baseline.value,112);
 assert.deepEqual(result.events.map(e=>[e.type,e.start,e.date]),[['initial','2026-11-01','2026-11-03'],['improved','2026-11-04','2026-11-06'],['regressed','2026-11-07','2026-11-09']]);
});
test('missing days expire candidates after seven calendar days and in-range measurements reset them',()=>{
 const r=automaticBaseline(days([100,100,100,110,null,null,null,null,null,null,110,110]),true);
 assert.equal(r.stages.length,1);
 assert.equal(r.states.get('2026-11-12').count,2);
 assert.equal(automaticBaseline(days([100,100,100,110,102,110,110]),true).stages.length,1);
});
test('lower latency is improvement; insufficient and zero baselines do not invent change',()=>{
 assert.equal(automaticBaseline(days([100,100,100,90,90,90]),false).stages[1].value,90);
 assert.equal(automaticBaseline(days([100,null,100]),true).initial,null);
 assert.equal(automaticBaseline(days([0,0,0,10,10,10]),true).stages.length,1);
});

import {trendTaskStates} from '../kanban/static/trends.mjs';
test('task failure is retained separately from measured performance and excludes other recipes',()=>{
 const runs=[run('a',100)];
 const jobs=[{...job('2026-11-01','a'),recipe_id:'m'}, {...job('2026-11-01',null,'FAILED','05'),recipe_id:'m'}, {...job('2026-11-02',null,'FAILED'),recipe_id:'other'}];
 const states=trendTaskStates(runs,jobs,seriesKey(runs[0]));
 assert.equal(states.get('2026-11-01').status,'FAILED');assert.equal(states.has('2026-11-02'),false);
 assert.equal(trendPoints(runs,jobs,seriesKey(runs[0]),'2026-11-01','day',1)[0].value,100);
});

import {trendScale} from '../kanban/static/trends.mjs';
test('ROM uses a baseline-centered range that exposes five-percent changes',()=>{
 const s=trendScale([281.49,281.50],'rom',281.49);
 assert.ok(s.min>0 && s.min<=281.49*.9);assert.ok(s.max>=281.49*1.1);assert.ok(s.max-s.min>=281.49*.2);assert.ok(s.ticks.length<=7);
 const speed=trendScale([35.1,35.2],'decode',35.1);
 assert.ok(speed.max-speed.min>=7.02);
 const regression=trendScale([35,20],'decode',35);
 assert.ok(regression.min<=20&&regression.max>=35);
});

test('default baseline filters four-percent changes and confirms six-percent gains',()=>{
 const result=automaticBaseline(days([100,100,100,104,104,104]),true);
 assert.equal(result.stages.length,1);
 assert.equal(automaticBaseline(days([100,100,100,106,106,106]),true).stages[1].value,106);
 assert.equal(automaticBaseline(days([100,100,100,102,102,102]),true).stages.length,1);
});

import {isBugRegression} from '../kanban/static/trends.mjs';
test('bug marking includes ten-percent degradation, never improvement or missing data',()=>{
 assert.equal(isBugRegression(improvement(100,90,true)),true);
 assert.equal(isBugRegression(improvement(100,110,false)),true);
 for(const v of [-9.9,10,null,undefined,NaN])assert.equal(isBugRegression(v),false);
});
