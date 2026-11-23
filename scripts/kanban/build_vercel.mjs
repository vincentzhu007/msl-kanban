import { readFile, readdir, mkdir, writeFile, copyFile, cp, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { installPerfetto } from './install_perfetto.mjs';

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
const auditDir=join(root,'kanban','audits');
let auditFiles=[];
try {auditFiles=await readdir(auditDir)} catch(error) {if(error.code!=='ENOENT')throw error}
const audits=[];
for(const file of auditFiles.filter(f=>f.endsWith('.record.json')).sort()){
  audits.push(JSON.parse(await readFile(join(auditDir,file),'utf8')));
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
html = replaceRequired(html, '服务端结果在页面可见时每 15 分钟刷新；新增 daily / weekly 结果可写入服务器数据目录。Daily 任务状态见下方记录。', '页面可见时每 15 分钟检查更新。Daily 任务状态见下方记录。');
let js = await readFile(join(source, 'app.js'), 'utf8');
js = replaceRequired(js, "fetch('/api/runs')", "fetch('/runs.json', {cache:'no-store'})");
js = replaceRequired(js, "fetch('/api/jobs')", "fetch('/jobs.json', {cache:'no-store'})");
await Promise.all([
  ...['playground.html', 'playground.css', 'trends.js', 'iteration.html', 'iteration.js', 'iteration-config.js', 'iteration.css', 'mindspore-logo.svg'].map(name => copyFile(join(source, name), join(output, name))),
  writeFile(join(output, 'jobs.json'), JSON.stringify(jobs, null, 2) + '\n'),
  writeFile(join(output, 'audits.json'), JSON.stringify(audits, null, 2) + '\n'),
  writeFile(join(output, 'detail.html'), html),
  copyFile(join(source, 'index.html'), join(output, 'index.html')),
  ...(await readdir(source)).filter(name => name.endsWith('.mjs')).map(name => copyFile(join(source, name), join(output, name))),
  writeFile(join(output, 'summary.js'), (await readFile(join(source, 'summary.js'), 'utf8')).replace("fetch('/api/runs')", "fetch('/runs.json', {cache:'no-store'})").replace("fetch('/api/jobs')", "fetch('/jobs.json', {cache:'no-store'})").replace("fetch('/api/audits')", "fetch('/audits.json', {cache:'no-store'})")),
  writeFile(join(output, 'app.js'), js),
  writeFile(join(output, 'runs.json'), JSON.stringify(results, null, 2) + '\n'),
  copyFile(join(source, 'style.css'), join(output, 'style.css')),
]);
await copyOperators();
console.log(`Built ${results.length} benchmark results in ${output}`);

async function copyOperators() {
  const operatorData = join(root, 'kanban', 'operator-data');
  const catalog = JSON.parse(await readFile(join(operatorData, 'catalog.json'), 'utf8'));
  if (catalog.schema_version !== 1) throw new Error('Unsupported operator catalog');
  const target = join(output, 'operator-data');
  await rm(target, {recursive: true, force: true});
  await mkdir(target, {recursive: true});
  const copied = new Set();
  async function copyData(path) {
    if (copied.has(path)) return;
    const dest = join(target, path);
    await mkdir(resolve(dest, '..'), {recursive: true});
    await copyFile(join(operatorData, path), dest);
    copied.add(path);
  }
  for (const [operator, platforms] of Object.entries(catalog.operators)) {
    for (const [platform, files] of Object.entries(platforms)) {
      for (const path of files) {
        if (!/^runs\/(?:[\w-]+\/){2}[\w-]+\.json$/.test(path) || copied.has(path)) {
          throw new Error(`Invalid or duplicate operator record: ${path}`);
        }
        const record = JSON.parse(await readFile(join(operatorData, path), 'utf8'));
        if (record.schema_version !== 1 || record.operator !== operator || record.platform !== platform ||
            path !== `runs/${operator}/${platform}/${record.id}.json`) {
          throw new Error(`Operator record does not match the catalog: ${path}`);
        }
        for (const item of [...record.cases, ...(record.simulations ?? [])]) {
          for (const trace of [item.trace, item.trace?.lifecycle, item.trace?.instructions].filter(Boolean)) {
            if (!/^[0-9a-f]{64}$/.test(trace.sha256) ||
                ![`traces/${trace.sha256}.json`, `traces/${trace.sha256}.json.gz`].includes(trace.file)) {
              throw new Error(`Invalid trace attachment: ${trace.file}`);
            }
            await copyData(trace.file);
          }
        }
        await copyData(path);
      }
    }
  }
  await copyData('catalog.json');
  const pageTarget = join(output, 'operators');
  await rm(pageTarget, {recursive: true, force: true});
  await cp(join(source, 'operators'), pageTarget, {recursive: true});
  if (process.argv.includes('--prepare-perfetto')) {
    await installPerfetto(join(pageTarget, 'viewer'));
  }
  await copyFile(join(source, 'operators.html'), join(output, 'operators.html'));
}
