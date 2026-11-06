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
from recipe_ci.device_ready import awake_device
from recipe_ci.planner import resolve, write_new
from recipe_ci.recipe import load, digest, sha256_file, require
from recipe_ci.results import summarize_recipe
from .model_export import export_model, source_manifest

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


class DeviceOfflineError(RuntimeError):
    """hdc could not reach the device; no device-side data was read."""


def device_output(env, command):
    completed = subprocess.run(['hdc', '-t', env['device']['serial'], 'shell', *command],
                               check=True, capture_output=True, text=True, timeout=20)
    output = completed.stdout.strip()
    # hdc reports connection errors such as "[Fail][E001005] Device not found or connected"
    # on stdout with exit code 0; never compare that text as if it were device output.
    if output.startswith('[Fail]') or (completed.stderr or '').lstrip().startswith('[Fail]'):
        detail = (output or completed.stderr.strip()).splitlines()[0]
        raise DeviceOfflineError('Device unreachable via hdc: ' + detail)
    return output


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
    if result.get('memory_samples'):
        measured = result['memory_samples'][0]['start_epoch_ms'] / 1000
        result['date'] = datetime.fromtimestamp(measured, timezone(timedelta(hours=8))).date().isoformat()
    result['model'].pop('provenance', None)
    result['device'] = device_alias
    result['source'] = 'daily 真机评测 · GitHub Actions'
    result['daily'] = {**build, 'code_commit': code_commit, 'task_url': task_url}
    source_note = '固定版本 llama.cpp 每日对照' if result.get('framework') == 'llama.cpp CPU' else 'Daily MSL 运行库'
    spec = result.get('spec', {})
    model_note = '当天 master daily 导出工具及算子重新生成模型' if build.get('model_generation') == 'master_daily' else '固定已归档模型'
    result['protocol_note'] = (source_note + '与本次重编译探针；' + model_note + '。上下文2048、输入1024、输出128，'
                               f"同进程连续{spec.get('consecutive_runs', len(result.get('samples', [])))}次，无预热；总PSS包含Graph。温度/频率未锁定，不自动批准性能基线。")
    if result.get('memory', {}).get('net_pss_kib'):
        result['protocol_note'] += ' RAM已扣除同PID加载Lite LLM动态库前的PSS中位数；原始总PSS保留。初始化包含动态库加载。'
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def prepare_msl(repo, config, build, task, cache):
    archive = download(build, cache)
    package_dir = task / 'package'
    safe_extract(archive, package_dir)
    libraries = list(package_dir.glob('*/lib/libmindspore-lite-llm.so'))
    require(len(libraries) == 1, 'Expected exactly one MSL runtime library')
    runtime = libraries[0].parent.parent
    native = Path(config['native'])
    probe = task / 'recipe-msl'
    command = [str(native / 'llvm/bin/clang++'), '--target=aarch64-linux-ohos',
               '--sysroot=' + str(native / 'sysroot'), '-std=c++17', '-O2', '-static-libstdc++',
               '-I', str(runtime / 'include'), str(repo / 'scripts/edge_slm_bench/bench_recipe.cc'),
               '-ldl', '-pthread', '-o', str(probe)]
    run_command(command, task / 'compile.log')
    shutil.copyfile(libraries[0], task / 'libmindspore-lite-llm.so')
    return archive, probe


def prepare_llama(repo, config, build, task):
    archive = Path(config['environment']['artifacts']['runtime']['host_path'])
    require(sha256_file(archive) == build['sha256'], 'Pinned llama source checksum mismatch')
    source = task / 'llama-source'
    safe_extract(archive, source)
    native = Path(config['native'])
    output = task / 'llama-build'
    compat = repo / 'scripts/edge_llama_bench/ohos_compat.h'
    flags = '-O3 -DNDEBUG -D_GNU_SOURCE -include ' + str(compat)
    command = ['cmake', '-S', str(repo / 'scripts/edge_llama_bench'), '-B', str(output),
               '-DLLAMA_CPP_DIR=' + str(source), '-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_TOOLCHAIN_FILE=' + str(native / 'build/cmake/ohos.toolchain.cmake'),
               '-DOHOS_ARCH=arm64-v8a', '-DOHOS_STL=c++_static',
               '-DCMAKE_C_FLAGS=' + flags, '-DCMAKE_CXX_FLAGS=' + flags,
               '-DBUILD_SHARED_LIBS=OFF', '-DGGML_NATIVE=OFF', '-DGGML_OPENMP=OFF',
               '-DGGML_CPU_KLEIDIAI=OFF', '-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod', '-DLLAMA_CURL=OFF', '-DLLAMA_BUILD_COMMON=OFF',
               '-DLLAMA_BUILD_TESTS=OFF', '-DLLAMA_BUILD_EXAMPLES=OFF', '-DLLAMA_BUILD_SERVER=OFF']
    run_command(command, task / 'configure.log', timeout=180)
    run_command(['cmake', '--build', str(output), '--target', 'recipe-llama', '-j', '4'],
                task / 'compile.log', timeout=1200)
    probe = task / 'recipe-llama'
    shutil.copyfile(output / 'recipe-llama', probe)
    probe.chmod(0o755)
    return archive, probe


def record_blocked(repo, config, day):
    """A dependency status, never a fabricated recipe or performance result."""
    name = config['task_id']
    require(bool(re.fullmatch(r'[a-z0-9-]+', name)), 'Invalid blocked task id')
    task_id = os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex[:12])
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    run_id = f'daily-{day}-{name}-{task_id}-{attempt}'
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    status = {'id': run_id, 'date': day, 'recipe_id': name, 'status': 'BLOCKED',
              'stage': 'PREREQUISITES', 'reason': config['blocked'],
              'started_at': now, 'finished_at': now,
              'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
              'task_url': f'https://github.com/vincentzhu007/msl-kanban/actions/runs/{task_id}' if task_id.isdigit() else None}
    write_json(Path(config['archive_root']) / 'tasks' / run_id / 'status.json', status)
    write_json(repo / 'kanban/jobs' / (run_id + '.json'), status)
    print('BLOCKED: ' + config['blocked'], flush=True)
    return 0


def run(repo, recipe_path, config, day, force=False):
    env = copy.deepcopy(config['environment'])
    recipe = load(recipe_path)
    backend = recipe['backend']['name']
    root = Path(config['archive_root'])
    task_id = os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex[:12])
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    run_id = f'daily-{day}-{recipe["id"]}-{task_id}-{attempt}'
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
        build = discover(day) if backend == 'msl' else dict(recipe['build'], sha256=config['environment']['artifacts']['runtime']['sha256'])
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
            source_identity = digest(source_manifest(Path(config['model_generation']['source_model']))) if backend == 'msl' and config.get('model_generation') else None
            key = digest({'source_model': source_identity, 'build': build, 'recipe': recipe, 'code': code, 'device': device_key, 'day': day, 'model_generation': config.get('model_generation')})
            marker = root / 'completed' / (key + '.json')
            if marker.exists() and not force:
                previous = json.loads(marker.read_text())
                result = json.loads(Path(previous['result']).read_text())
                write_json(repo / 'kanban/data' / (result['id'] + '.json'), result)
                update(status='SKIPPED', result_id=result['id'], stage='ARCHIVED')
                return 0
            archive, probe = (prepare_msl(repo, config, build, task, root / 'packages')
                              if backend == 'msl' else prepare_llama(repo, config, build, task))
            regenerated = backend == 'msl' and bool(config.get('model_generation'))
            if regenerated:
                update(stage='EXPORT_MODEL')
                recipe, components = export_model(repo, recipe, env, config, task, build, run_command, write_json)
                build = dict(build, model_generation='master_daily', daily_components=components)
            native = Path(config['native'])
            write_json(task / 'toolchain.json', {'compiler': subprocess.check_output(
                [str(native / 'llvm/bin/clang++'), '--version'], text=True),
                'compiler_sha256': sha256_file(native / 'llvm/bin/clang++'),
                'binrunner_commit': subprocess.check_output(['git', '-C', env['binrunner'], 'rev-parse', 'HEAD'], text=True).strip()})
            recipe['build'] = {**{k: build[k] for k in ['commit', 'source_url', 'sha256'] if k in build}, **({'components': recipe['build']['components']} if 'components' in recipe['build'] else {})}
            recipe['description'] = ('Master daily exporter/operators regenerated model' if regenerated else 'Daily runtime with fixed archived model')
            env['output_root'] = str(root / 'runs')
            env['artifacts']['probe'] = {'host_path': str(probe), 'device_path': '@/bin/' + probe.name, 'sha256': sha256_file(probe)}
            env['artifacts']['runtime'] = {'host_path': str(archive), 'sha256': build['sha256']}
            if backend == 'msl':
                runtime_so = task / 'libmindspore-lite-llm.so'
                env['artifacts']['runtime_so'] = {'host_path': str(runtime_so), 'device_path': '@/bin/' + runtime_so.name, 'sha256': sha256_file(runtime_so)}
            lock = resolve(recipe, env)
            write_new(task / 'resolved-recipe.json', lock)
            write_json(task / 'environment.json', env)
            write_json(task / 'recipe.json', recipe)
            processes = device_output(env, ['ps', '-A', '-o', 'PID,COMM'])
            require(not any(line.split()[-1].strip('[]') in {'recipe-msl', 'recipe-llama', 'edge-llama'}
                            for line in processes.splitlines() if line.split()), 'Device worker still running')
            prefix = ['python3', '-m', 'binrunner', '-t', env['device']['serial'], '-p', env['device']['port']]
            update(stage='DEPLOY')
            ensure_forward(env, config.get('binrunner_device_port', 8888))
            with awake_device(env['device']['serial']):
                run_command(prefix + ['push', str(probe)], task / 'push.log', cwd=env['binrunner'])
                if backend == 'msl':
                    run_command(prefix + ['push', str(runtime_so)], task / 'push-runtime.log', cwd=env['binrunner'], timeout=300)
                if regenerated:
                    # BinRunner push defaults to basename; match the locked device path exactly.
                    deployed = task / Path(env['artifacts']['model']['device_path']).name
                    os.link(env['artifacts']['model']['host_path'], deployed)
                    run_command(prefix + ['push', str(deployed)], task / 'push-model.log', cwd=env['binrunner'], timeout=600)
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
        if isinstance(error, DeviceOfflineError):
            reason = '测试真机离线（hdc 无法连接），未执行测量，未发布新的性能结果。'
        elif status['stage'] == 'EXPORT_MODEL':
            reason = '当日 master daily 模型生成失败；未回退旧模型，完整日志保存在 dog。'
        else:
            reason = '任务未通过校验，未发布新的性能结果。'
        update(status='FAILED', error_type=type(error).__name__, reason=reason)
        print(f'Daily failed at {status["stage"]}: {error}', flush=True)
        return 1
    finally:
        status['finished_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        write_json(task / 'status.json', status)
        write_json(repo / 'kanban/jobs' / (run_id + '.json'), status)
