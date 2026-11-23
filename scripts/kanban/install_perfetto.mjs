import {createHash} from 'node:crypto';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const version = 'v59.1-491832c0d';
const upstream = `https://ui.perfetto.dev/${version}/`;
const bootstrap = {
  'index.html': '33ae569b0cfd7ed66b2be9f649de4aaadae0dd42177643a552460a6225d2da99',
  'manifest.json': '5b7c5eea44cd954dc5338f302bb347d3e8c866ac32c762b266e81a57b632258d',
};
const licenseURL = 'https://raw.githubusercontent.com/google/perfetto/491832c0d/LICENSE';
const licenseHash = '9b569417be9f195f8ffa709a23836c4e0f880b2752b09653baa8a98d3b02db3a';

function integrity(bytes) {
  return 'sha256-' + createHash('sha256').update(bytes).digest('base64');
}

function hexIntegrity(hex) {
  return 'sha256-' + Buffer.from(hex, 'hex').toString('base64');
}

async function install(file, url, expected) {
  const current = await readFile(file).catch(error => {
    if (error.code !== 'ENOENT') throw error;
  });
  if (current && integrity(current) === expected) return;

  let lastError;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(url, {signal: AbortSignal.timeout(45_000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = Buffer.from(await response.arrayBuffer());
      if (integrity(bytes) !== expected) throw new Error('SHA-256 mismatch');
      await mkdir(dirname(file), {recursive: true});
      await writeFile(file, bytes);
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`Failed to install Perfetto resource ${url}: ${lastError.message}`, {cause: lastError});
}

export async function installPerfetto(target) {
  const directory = join(target, version);
  await Promise.all([
    install(join(target, 'LICENSE'), licenseURL, hexIntegrity(licenseHash)),
    ...Object.entries(bootstrap).map(([name, hash]) =>
      install(join(directory, name), upstream + name, hexIntegrity(hash))),
  ]);
  const manifest = JSON.parse(await readFile(join(directory, 'manifest.json'), 'utf8'));
  const resources = Object.entries(manifest.resources);
  const batchSize = 6;
  for (let start = 0; start < resources.length; start += batchSize) {
    await Promise.all(resources.slice(start, start + batchSize).map(([name, hash]) =>
      install(join(directory, name), upstream + name, hash)));
  }
  console.log(`Perfetto ${version}: ${resources.length} verified resources`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const target = fileURLToPath(new URL('../../kanban/static/operators/viewer/', import.meta.url));
  await installPerfetto(target);
}
