import { readFile, readdir, mkdir, writeFile, copyFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const source = join(root, 'kanban', 'static');
const data = join(root, 'kanban', 'data');
const output = join(root, 'build', 'vercel-kanban');
const replaceRequired = (text, from, to) => {
  if (!text.includes(from)) throw new Error(`Missing kanban template marker: ${from}`);
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
const jobsDir=join(root,'kanban','jobs');
let jobFiles=[];
try {jobFiles=await readdir(jobsDir)} catch(error) {if(error.code!=='ENOENT')throw error}
const jobs=[];
for(const file of jobFiles.filter(f=>f.endsWith('.json')).sort()){
  const job=JSON.parse(await readFile(join(jobsDir,file),'utf8'));
  if(!job.id||!job.status||!job.stage||!job.started_at)throw new Error(`Invalid daily job: ${file}`);
  jobs.push(job);
}
await mkdir(output, { recursive: true });
let html = await readFile(join(source, 'detail.html'), 'utf8');
html = replaceRequired(html, 'DOG · Docker 部署', '性能数据看板');
html = replaceRequired(html, '服务端结果每 60 秒刷新；新增 daily / weekly 结果可写入服务器数据目录。Daily 任务状态见下方记录。', '结果随网站发布更新；导入数据保存在当前浏览器。Daily 任务状态见下方记录。');
let js = await readFile(join(source, 'app.js'), 'utf8');
js = replaceRequired(js, "fetch('/api/runs')", "fetch('/runs.json', {cache:'no-store'})");
js = replaceRequired(js, "fetch('/api/jobs')", "fetch('/jobs.json', {cache:'no-store'})");
await Promise.all([
  writeFile(join(output, 'jobs.json'), JSON.stringify(jobs, null, 2) + '\n'),
  writeFile(join(output, 'detail.html'), html),
  copyFile(join(source, 'index.html'), join(output, 'index.html')),
  copyFile(join(source, 'summary-model.mjs'), join(output, 'summary-model.mjs')),
  writeFile(join(output, 'summary.js'), (await readFile(join(source, 'summary.js'), 'utf8')).replace("fetch('/api/runs')", "fetch('/runs.json', {cache:'no-store'})").replace("fetch('/api/jobs')", "fetch('/jobs.json', {cache:'no-store'})")),
  writeFile(join(output, 'app.js'), js),
  writeFile(join(output, 'runs.json'), JSON.stringify(results, null, 2) + '\n'),
  copyFile(join(source, 'style.css'), join(output, 'style.css')),
]);
console.log(`Built ${results.length} benchmark results in ${output}`);
