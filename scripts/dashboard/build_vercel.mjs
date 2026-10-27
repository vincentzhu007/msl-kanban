import { readFile, readdir, mkdir, writeFile, copyFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const source = join(root, 'dashboard', 'static');
const data = join(root, 'dashboard', 'data');
const output = join(root, 'build', 'vercel-dashboard');
const replaceRequired = (text, from, to) => {
  if (!text.includes(from)) throw new Error(`Missing dashboard template marker: ${from}`);
  return text.replace(from, to);
};
const files = (await readdir(data)).filter(name => name.endsWith('.json')).sort();
if (!files.length) throw new Error('No benchmark results found');
const ids = new Set();
const results = [];
for (const file of files) {
  const result = JSON.parse(await readFile(join(data, file), 'utf8'));
  if (!result.id || !result.spec || !result.timing || !Array.isArray(result.samples)) {
    throw new Error(`Invalid benchmark result: ${file}`);
  }
  if (ids.has(result.id)) throw new Error(`Duplicate result id: ${result.id}`);
  ids.add(result.id);
  results.push(result);
}
await mkdir(output, { recursive: true });
let html = await readFile(join(source, 'index.html'), 'utf8');
html = replaceRequired(html, 'DOG · Docker 部署', '性能数据看板');
html = replaceRequired(html, '<a href="/auth/account">登录账号</a>', '');
html = replaceRequired(html, '服务端结果每 60 秒刷新；新增 daily / weekly 结果可写入服务器数据目录。自动评测调度尚未接入。', '结果随网站发布更新；导入数据保存在当前浏览器。自动评测调度尚未接入。');
let js = await readFile(join(source, 'app.js'), 'utf8');
js = replaceRequired(js, "fetch('/api/runs')", "fetch('/runs.json', {cache:'no-store'})");
await Promise.all([
  writeFile(join(output, 'index.html'), html),
  writeFile(join(output, 'app.js'), js),
  writeFile(join(output, 'runs.json'), JSON.stringify(results, null, 2) + '\n'),
  copyFile(join(source, 'style.css'), join(output, 'style.css')),
]);
console.log(`Built ${results.length} benchmark results in ${output}`);
