import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, cpSync, readdirSync, readFileSync, existsSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
test('clean Vercel build includes every local JavaScript module dependency', () => {
  const dir = mkdtempSync(join(tmpdir(), 'kanban-build-test-'));
  try {
    for (const path of ['kanban', 'scripts/kanban']) cpSync(join(root, path), join(dir, path), {recursive: true});
    execFileSync(process.execPath, ['scripts/kanban/build_vercel.mjs'], {cwd: dir});
    const output = join(dir, 'build/vercel-kanban');
    for (const name of readdirSync(output).filter(n => /\.(m?js)$/.test(n))) {
      const source = readFileSync(join(output, name), 'utf8');
      for (const match of source.matchAll(/\b(?:from\s*|import\s*)['"](\.\.?\/[^'"]+)['"]/g)) {
        assert.ok(existsSync(join(output, match[1])), `${name} imports missing ${match[1]}`);
      }
    }
    const read = name => readFileSync(join(output, name), 'utf8');
    const visible = read('visible-refresh.mjs');
    const sourceVisible = readFileSync(join(dir, 'kanban/static/visible-refresh.mjs'), 'utf8');
    const app = read('app.js');
    const summary = read('summary.js');
    const index = read('index.html');
    const detail = read('detail.html');
    assert.equal(visible, sourceVisible);
    assert.match(visible, /export const AUTO_REFRESH_MS = 15 \* 60 \* 1000/);
    assert.match(visible, /jobs: 0/);
    assert.match(sourceVisible, /jobs: 0/);
    assert.doesNotMatch(app, /setInterval/);
    assert.doesNotMatch(summary, /setInterval/);
    assert.doesNotMatch(app, /60 秒/);
    assert.doesNotMatch(summary, /60 秒/);
    assert.doesNotMatch(index, /60 秒/);
    assert.doesNotMatch(detail, /60 秒/);
    assert.match(app, /fetch\('\/runs\.json', \{cache:'no-store'\}\)/);
    assert.match(app, /fetch\('\/jobs\.json', \{cache:'no-store'\}\)/);
    assert.match(summary, /fetch\('\/runs\.json', \{cache:'no-store'\}\)/);
    assert.match(summary, /fetch\('\/jobs\.json', \{cache:'no-store'\}\)/);
    assert.match(summary, /bindAutoRefresh\(\(\) => refresh\('runs'\), refreshPolicy\.runs\)/);
    assert.match(app, /bindAutoRefresh\(refresh, refreshPolicy\.runs\)/);
    assert.match(app, /bindAutoRefresh\(refreshJobs, refreshPolicy\.jobs\)/);
    assert.match(index, /性能结果在页面可见时每 15 分钟检查更新/);
    assert.match(detail, /页面可见时每 15 分钟检查更新/);
    assert.doesNotMatch(detail, /写入服务器数据目录/);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
