"""Consume a verified MSL daily package and run the existing frozen-model recipe."""
import copy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import time
import subprocess
import tarfile
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import urlopen
import uuid

from recipe_ci.execution import device_lease, execute
from recipe_ci.planner import resolve, write_new
from recipe_ci.recipe import load, digest, sha256_file, require
from recipe_ci.results import summarize_recipe

BASE_URL = 'https://repo.mindspore.cn/mindspore/mindspore-lite/version/'
PACKAGE = 'mindspore-lite-llm-linux-x64-0.2.0.tar.gz'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(v for k, v in attrs if k == 'href' and v)


def select_build(html, day):
    parser = Links()
    parser.feed(html)
    pattern = re.compile(r'master_(' + day + r'\d{6})_([a-f0-9]{40})_newest/?$')
    matches = [(m[1], m[2], href) for href in parser.hrefs if (m := pattern.fullmatch(href))]
    return max(matches) if matches else None


def fetch(url):
    with urlopen(url, timeout=60) as response:
        return response.read()


def discover(day):
    directory = f'{BASE_URL}{day[:6]}/{day}/'
    try:
        selected = select_build(fetch(directory).decode(), day)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not selected:
        return None
    stamp, commit, entry = selected
    url = urljoin(directory, entry.rstrip('/') + '/lite/ohos_aarch64/' + PACKAGE)
    checksum = fetch(url + '.sha256').decode().strip().split()[0]
    require(bool(re.fullmatch(r'[0-9a-fA-F]{64}', checksum)), 'Invalid upstream SHA256')
    return {'commit': commit, 'source_url': url, 'sha256': checksum.lower()}


def safe_extract(archive, destination):
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            require(not path.is_absolute() and '..' not in path.parts, 'Unsafe package path')
            require(member.isfile() or member.isdir(), 'Package links and special files are unsupported')
        bundle.extractall(destination, members=members)


def download(build, cache):
    directory = cache / build['sha256']
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / PACKAGE
    if not archive.exists() or sha256_file(archive) != build['sha256']:
        temporary = directory / 'download.part'
        with urlopen(build['source_url'], timeout=120) as response, temporary.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        require(sha256_file(temporary) == build['sha256'], 'Downloaded package SHA256 mismatch')
        temporary.replace(archive)
    return archive


def run_command(command, log, *, cwd=None, timeout=180):
    with log.open('w') as stream:
        stream.write(json.dumps(command) + '\n')
        stream.flush()
        subprocess.run(command, cwd=cwd, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)


def device_output(env, command):
    return subprocess.run(['hdc', '-t', env['device']['serial'], 'shell', *command],
                          check=True, capture_output=True, text=True, timeout=20).stdout.strip()


def ensure_forward(env, remote_port):
    """Reconcile only this task's local port; never replace another device's mapping."""
    serial, port = env['device']['serial'], env['device']['port']
    require(str(remote_port).isdigit(), 'Invalid BinRunner device port')
    prefix = ['hdc', '-t', serial, 'fport']
    expected = [serial, 'tcp:' + port, 'tcp:' + str(remote_port)]
    listed = subprocess.check_output(prefix + ['ls'], text=True, timeout=15)
    for line in listed.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == expected[1]:
            require(fields[0] == serial, 'BinRunner host port is owned by another device')
            if fields[:3] == expected:
                return
            subprocess.run(prefix + ['rm', fields[1], fields[2]], check=True,
                           capture_output=True, text=True, timeout=15)
    subprocess.Popen(prefix + expected[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(30):
        listed = subprocess.check_output(prefix + ['ls'], text=True, timeout=10)
        if any(line.split()[:3] == expected for line in listed.splitlines()):
            return
        time.sleep(.2)
    raise RuntimeError('BinRunner forwarding did not become ready')


def public_result(result, run_id, build, code_commit, device_alias, task_url):
    result = copy.deepcopy(result)
    result['id'] = run_id
    result['model'].pop('provenance', None)
    result['device'] = device_alias
    result['source'] = 'daily 真机评测 · GitHub Actions'
    result['daily'] = {**build, 'code_commit': code_commit, 'task_url': task_url}
    result['protocol_note'] = ('Daily 运行库与本次重编译探针；固定已归档模型。上下文2048、输入1024、输出128，'
                               '同进程连续5次，无预热；总PSS包含Graph。温度/频率未锁定，不自动批准性能基线。')
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def run(repo, recipe_path, config, day, force=False):
    env = copy.deepcopy(config['environment'])
    recipe = load(recipe_path)
    require(recipe['backend']['name'] == 'msl' and recipe['device_pool'] == 'Kirin9020',
            'Initial daily pipeline supports the MSL Kirin9020 recipe only')
    root = Path(config['archive_root'])
    task_id = os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex[:12])
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    run_id = f'daily-{day}-{task_id}-{attempt}'
    task = root / 'tasks' / run_id
    task.mkdir(parents=True, exist_ok=False)
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    task_url = f'https://github.com/vincentzhu007/msl-kanban/actions/runs/{task_id}' if task_id.isdigit() else None
    status = {'id': run_id, 'date': day, 'recipe_id': recipe['id'], 'code_commit': code,
              'task_url': task_url, 'status': 'RUNNING', 'stage': 'DISCOVER',
              'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat()}

    def update(**values):
        status.update(values)
        write_json(task / 'status.json', status)
        print(json.dumps({'status': status['status'], 'stage': status['stage']}, ensure_ascii=False), flush=True)

    try:
        update()
        run_command(['git', 'archive', '--format=tar.gz', '--output=' + str(task / 'source.tar.gz'), code], task / 'source.log', cwd=repo)
        build = discover(day)
        if build is None:
            update(status='NO_BUILD')
            return 0
        status['build_commit'] = build['commit']
        status['build_sha256'] = build['sha256']
        write_json(task / 'build.json', build)
        # Shared across all daily tasks: preparation/deployment must also own the device lease.
        with device_lease(root / 'leases', env['device']['serial']):
            update(stage='PREPARE')
            actual_os = device_output(env, ['param', 'get', 'const.ohos.fullname'])
            require(actual_os == env['device']['os_version'], 'Device OS differs from configured environment')
            device_key = digest(env['device'])
            key = digest({'build': build, 'recipe': recipe, 'code': code, 'device': device_key})
            marker = root / 'completed' / (key + '.json')
            if marker.exists() and not force:
                previous = json.loads(marker.read_text())
                result = json.loads(Path(previous['result']).read_text())
                write_json(repo / 'kanban/data' / (result['id'] + '.json'), result)
                update(status='SKIPPED', result_id=result['id'], stage='ARCHIVED')
                return 0
            archive = download(build, root / 'packages')
            package_dir = task / 'package'
            safe_extract(archive, package_dir)
            libraries = list(package_dir.glob('*/lib/libmindspore-lite-llm.a'))
            require(len(libraries) == 1, 'Expected exactly one MSL runtime library')
            runtime = libraries[0].parent.parent
            native = Path(config['native'])
            probe = task / 'recipe-msl'
            command = [str(native / 'llvm/bin/clang++'), '--target=aarch64-linux-ohos',
                       '--sysroot=' + str(native / 'sysroot'), '-std=c++17', '-O2', '-static-libstdc++',
                       '-I', str(runtime / 'include'), str(repo / 'scripts/edge_slm_bench/bench_recipe.cc'),
                       '-Wl,--whole-archive', str(libraries[0]), '-Wl,--no-whole-archive',
                       '-ldl', '-pthread', '-o', str(probe)]
            run_command(command, task / 'compile.log')
            write_json(task / 'toolchain.json', {'compiler': subprocess.check_output(
                [str(native / 'llvm/bin/clang++'), '--version'], text=True),
                'compiler_sha256': sha256_file(native / 'llvm/bin/clang++'),
                'binrunner_commit': subprocess.check_output(['git', '-C', env['binrunner'], 'rev-parse', 'HEAD'], text=True).strip()})
            recipe['build'] = build
            recipe['description'] = 'Daily runtime with fixed archived model; compiled recipe probe'
            env['output_root'] = str(root / 'runs')
            env['artifacts']['probe'] = {'host_path': str(probe), 'device_path': '@/bin/recipe-msl', 'sha256': sha256_file(probe)}
            env['artifacts']['runtime'] = {'host_path': str(archive), 'sha256': build['sha256']}
            lock = resolve(recipe, env)
            write_new(task / 'resolved-recipe.json', lock)
            write_json(task / 'environment.json', env)
            write_json(task / 'recipe.json', recipe)
            processes = device_output(env, ['ps', '-A', '-o', 'PID,COMM'])
            require(not any(line.split()[-1].strip('[]') == 'recipe-msl'
                            for line in processes.splitlines() if line.split()), 'Device worker still running')
            prefix = ['python3', '-m', 'binrunner', '-t', env['device']['serial'], '-p', env['device']['port']]
            update(stage='DEPLOY')
            ensure_forward(env, config.get('binrunner_device_port', 8888))
            run_command(prefix + ['push', str(probe)], task / 'push.log', cwd=env['binrunner'])
            update(stage='MEASURE')
            output = execute(lock)
            update(stage='VALIDATE')
            result = summarize_recipe(recipe, output, run_id=run_id)
            require(result['verification']['artifact_identity'], 'Device artifact identity was not verified')
            result = public_result(result, run_id, build, code, config['device_alias'], task_url)
            write_new(output / 'kanban-result.json', result)
            write_json(task / 'archive.json', {'measurement_dir': str(output)})
            write_json(repo / 'kanban/data' / (run_id + '.json'), result)
            write_json(marker, {'result': str(output / 'kanban-result.json'), 'run_id': run_id})
            update(status='SUCCEEDED', stage='ARCHIVED', result_id=run_id)
            return 0
    except Exception as error:
        # Full errors stay on dog; the public status contains only stage and exception type.
        (task / 'error.txt').write_text(str(error))
        update(status='FAILED', error_type=type(error).__name__)
        print(f'Daily failed at {status["stage"]}: {error}', flush=True)
        return 1
    finally:
        status['finished_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        write_json(task / 'status.json', status)
        write_json(repo / 'kanban/jobs' / (run_id + '.json'), status)
