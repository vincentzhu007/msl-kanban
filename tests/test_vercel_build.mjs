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
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
