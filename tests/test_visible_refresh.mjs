import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { autoRefreshTargets, bindAutoRefresh, AUTO_REFRESH_MS } from '../kanban/static/visible-refresh.mjs';

const FIFTEEN = 15 * 60 * 1000;

function fakeDocument(hidden = false) {
  const listeners = new Set();
  return {
    hidden,
    addEventListener(type, fn) {
      if (type === 'visibilitychange') listeners.add(fn);
    },
    removeEventListener(type, fn) {
      if (type === 'visibilitychange') listeners.delete(fn);
    },
    emit() {
      for (const fn of [...listeners]) fn();
    },
    listenerCount() {
      return listeners.size;
    },
  };
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

test.beforeEach(() => {
  mock.timers.enable({ apis: ['setTimeout', 'Date'] });
});

test.afterEach(() => {
  mock.timers.reset();
});

test('job polling is off and result refresh is 15 minutes', () => {
  assert.equal(AUTO_REFRESH_MS, FIFTEEN);
  assert.deepEqual(autoRefreshTargets(), { runs: FIFTEEN, jobs: 0 });
  assert.notEqual(autoRefreshTargets().runs, 60000);
});

test('a disabled interval never refreshes and adds no listener', async () => {
  const doc = fakeDocument();
  let calls = 0;
  const stop = bindAutoRefresh(async () => { calls += 1; }, 0, doc);
  mock.timers.tick(FIFTEEN * 4);
  doc.hidden = false;
  doc.emit();
  await flush();
  assert.equal(calls, 0);
  assert.equal(doc.listenerCount(), 0);
  stop();
});

test('visible refresh waits 15 minutes and then repeats', async () => {
  const doc = fakeDocument();
  let calls = 0;
  bindAutoRefresh(async () => { calls += 1; }, FIFTEEN, doc);
  mock.timers.tick(0);
  await flush();
  assert.equal(calls, 0);
  mock.timers.tick(60000);
  await flush();
  assert.equal(calls, 0);
  mock.timers.tick(FIFTEEN - 60000);
  await flush();
  assert.equal(calls, 1);
  mock.timers.tick(FIFTEEN);
  await flush();
  assert.equal(calls, 2);
  assert.equal(doc.listenerCount(), 1);
});

test('a hidden page does not refresh, and one return refreshes once', async () => {
  const doc = fakeDocument();
  let calls = 0;
  bindAutoRefresh(async () => { calls += 1; }, FIFTEEN, doc);
  doc.hidden = true;
  doc.emit();
  mock.timers.tick(FIFTEEN * 3);
  await flush();
  assert.equal(calls, 0);
  doc.hidden = false;
  doc.emit();
  mock.timers.tick(0);
  await flush();
  assert.equal(calls, 1);
  mock.timers.tick(FIFTEEN);
  await flush();
  assert.equal(calls, 2);
});

test('rapid visibility changes do not stack refreshes', async () => {
  const doc = fakeDocument();
  let calls = 0;
  bindAutoRefresh(async () => { calls += 1; }, FIFTEEN, doc);
  for (let i = 0; i < 30; i += 1) {
    doc.hidden = true;
    doc.emit();
    doc.hidden = false;
    doc.emit();
  }
  mock.timers.tick(FIFTEEN - 1);
  await flush();
  assert.equal(calls, 0);
  assert.equal(doc.listenerCount(), 1);
  mock.timers.tick(1);
  await flush();
  assert.equal(calls, 1);
});

test('an in-flight refresh is not repeated by another tick or visibility storm', async () => {
  const doc = fakeDocument();
  let calls = 0;
  let release;
  const refresh = () => new Promise(resolve => {
    calls += 1;
    release = resolve;
  });
  bindAutoRefresh(refresh, FIFTEEN, doc);
  mock.timers.tick(FIFTEEN);
  assert.equal(calls, 1);
  for (let i = 0; i < 10; i += 1) {
    doc.hidden = true;
    doc.emit();
    doc.hidden = false;
    doc.emit();
  }
  mock.timers.tick(1000);
  await flush();
  assert.equal(calls, 1);
  release();
  await flush();
  mock.timers.tick(FIFTEEN - 1000 - 1);
  await flush();
  assert.equal(calls, 1);
  mock.timers.tick(1);
  await flush();
  assert.equal(calls, 2);
});

test('a failed refresh still runs on the next interval', async () => {
  const doc = fakeDocument();
  let calls = 0;
  bindAutoRefresh(async () => {
    calls += 1;
    if (calls === 1) throw new Error('unavailable');
  }, FIFTEEN, doc);
  mock.timers.tick(FIFTEEN);
  await flush();
  assert.equal(calls, 1);
  mock.timers.tick(FIFTEEN);
  await flush();
  assert.equal(calls, 2);
});

test('cleanup ignores later timers and visibility changes', async () => {
  const doc = fakeDocument();
  let calls = 0;
  const stop = bindAutoRefresh(async () => { calls += 1; }, FIFTEEN, doc);
  stop();
  for (let i = 0; i < 5; i += 1) {
    doc.hidden = i % 2 === 0;
    doc.emit();
  }
  mock.timers.tick(FIFTEEN * 4);
  await flush();
  assert.equal(calls, 0);
  assert.equal(doc.listenerCount(), 0);
});

test('homepage and detail keep result refresh and drop job polling', () => {
  const summary = readFileSync(new URL('../kanban/static/summary.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../kanban/static/app.js', import.meta.url), 'utf8');
  assert.match(summary, /bindAutoRefresh\(\(\) => refresh\('runs'\), refreshPolicy\.runs\)/);
  assert.match(summary, /fetch\('\/api\/runs'\)/);
  assert.match(summary, /fetch\('\/api\/jobs'\)/);
  assert.doesNotMatch(summary, /setInterval/);
  assert.match(app, /bindAutoRefresh\(refresh, refreshPolicy\.runs\)/);
  assert.match(app, /bindAutoRefresh\(refreshJobs, refreshPolicy\.jobs\)/);
  assert.doesNotMatch(app, /setInterval/);
  assert.doesNotMatch(summary, /60 秒/);
  assert.doesNotMatch(app, /60 秒/);
});
