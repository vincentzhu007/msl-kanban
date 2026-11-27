"""Consume a verified MSL daily package and run the existing frozen-model recipe."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import math
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
from recipe_ci.results import summarize_recipe, unstable_baseline_warning
from .model_export import export_model, source_manifest
from .safe_transport import (
    SAFE_TASKS, SafeTransportError, listening_tcp_ports, open_safe_session, plan_host_port,
    read_fport_listing, requires_safe_norestart, sandbox_basename,
)

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


def download(build, cache, *, require_cached=False):
    directory = cache / build['sha256']
    if require_cached:
        archive = directory / PACKAGE
        require(archive.is_file(), 'Locked package is missing from cache')
        require(sha256_file(archive) == build['sha256'], 'Locked package SHA256 mismatch')
        return archive
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / PACKAGE
    if not archive.exists() or sha256_file(archive) != build['sha256']:
        temporary = directory / 'download.part'
        with urlopen(build['source_url'], timeout=120) as response, temporary.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        require(sha256_file(temporary) == build['sha256'], 'Downloaded package SHA256 mismatch')
        temporary.replace(archive)
    return archive


_LOCK_URL = re.compile(
    re.escape(BASE_URL) +
    r'(?P<month>[0-9]{6})/(?P<day>[0-9]{8})/master_(?P=day)[0-9]{6}_'
    r'(?P<commit>[0-9a-f]{40})_newest/lite/ohos_aarch64/' + re.escape(PACKAGE) + r'$'
)


def select_msl_build(config, recipe_id, day, cache):
    """Use an explicit package lock, or discover the requested run day.

    `package_lock.day` records the date embedded in the official package URL.
    It is not the calendar day of this run and is not compared to `day`.
    """
    if 'package_lock' not in config:
        return discover(day)
    require(recipe_id in SAFE_TASKS, 'Package locks are limited to the two 1.5B backfill tasks')
    lock = config['package_lock']
    require(isinstance(lock, dict) and set(lock) == {'day', 'commit', 'source_url', 'sha256'},
            'Package lock needs exactly day, commit, source_url, sha256')
    require(isinstance(lock['day'], str) and bool(re.fullmatch(r'[0-9]{8}', lock['day'])),
            'Invalid package lock day record')
    require(isinstance(lock['sha256'], str) and bool(re.fullmatch(r'[0-9a-f]{64}', lock['sha256'])),
            'Invalid locked SHA256')
    require(isinstance(lock['commit'], str) and bool(re.fullmatch(r'[0-9a-f]{40}', lock['commit'])),
            'Invalid locked commit')
    require(isinstance(lock['source_url'], str), 'Locked URL must be a string')
    matched = _LOCK_URL.fullmatch(lock['source_url'])
    require(matched is not None, 'Locked URL must match the official day, commit, platform and package')
    require(matched.group('month') == lock['day'][:6] and matched.group('day') == lock['day'],
            'Package lock day record does not match the URL path')
    require(matched.group('commit') == lock['commit'], 'Locked commit does not match the URL')
    build = {key: lock[key] for key in ('commit', 'source_url', 'sha256')}
    download(build, cache, require_cached=True)
    return build


def run_command(command, log, *, cwd=None, timeout=180):
    with log.open('w') as stream:
        stream.write(json.dumps(command) + '\n')
        stream.flush()
        subprocess.run(command, cwd=cwd, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)


# Model-push budget measured on 2026-11-12 (Asia/Shanghai) against BinRunner
# 1.4.1 on dog's Kirin9030 path: about 3.07 MiB/s. A 1999.315 MiB Qwen3-4B
# .msl package was at 92% (1841.5 MiB) when the old 600s cap killed the
# subprocess; about 51s more would have finished. A 281.5 MiB w4a16 push
# succeeded at ~3.1 MiB/s. Budget at a conservative 2.0 MiB/s times 1.3,
# with a 600s floor: 1999.315 MiB lands at 1300s and 2285402624 bytes
# (about 2.13 GiB) lands at 1417s.
PUSH_TIMEOUT_FLOOR_SECONDS = 600
PUSH_TIMEOUT_RATE_BYTES_PER_SECOND = 2 * 1024 * 1024
PUSH_TIMEOUT_MARGIN = 1.3
PUSH_TIMEOUT_RETRIES = 1  # one extra br push after a host-side timeout


def push_timeout_seconds(size_bytes):
    require(isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes >= 0,
            'Model size must be a non-negative int')
    estimated = math.ceil(size_bytes / PUSH_TIMEOUT_RATE_BYTES_PER_SECOND * PUSH_TIMEOUT_MARGIN)
    return max(PUSH_TIMEOUT_FLOOR_SECONDS, int(estimated))


def push_with_resume(command, log, *, cwd, size_bytes):
    """Push a large model and retry once after a host-side timeout.

    BinRunner 1.4.1 ``br push FILE`` has no resume CLI flag. ``push_file()``
    always calls ``_open_and_send(..., resume=True)``, so a second invocation
    of the same command renegotiates the device offset from the existing
    ``.part`` file (v2 header + 64KiB probe). Internal ``RESUME_MAX_ATTEMPTS``
    (5) only covers mid-transfer OSError inside one process, not this
    process-level timeout.
    """
    timeout = push_timeout_seconds(size_bytes)
    attempts = 1 + PUSH_TIMEOUT_RETRIES
    for attempt in range(1, attempts + 1):
        mode = 'w' if attempt == 1 else 'a'
        with log.open(mode) as stream:
            if attempt == 1:
                stream.write(json.dumps(command) + '\n')
            stream.write(json.dumps({
                'push_attempt': attempt, 'push_attempts': attempts,
                'timeout_seconds': timeout, 'size_bytes': size_bytes,
            }) + '\n')
            stream.flush()
            try:
                subprocess.run(command, cwd=cwd, check=True, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                stream.write(
                    f'\nDaily model push timed out after {timeout}s '
                    f'(attempt {attempt}/{attempts})\n')
                stream.flush()
                if attempt == attempts:
                    raise
                stream.write(
                    'Retrying the same BinRunner push command; resume is the '
                    'default in 1.4.1 and needs no extra flag.\n')
                stream.flush()


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
    if unstable_baseline_warning(result.get('memory') or {}):
        result['protocol_note'] += (' 基线 PSS 极差超过稳定阈值，净 PSS 未计算，未扣除底噪。'
                                    '原始总 PSS 与基线 min/median/max 保留。初始化包含模型创建。')
    elif result.get('memory', {}).get('net_pss_kib'):
        result['protocol_note'] += ' RAM已扣除同PID创建模型前的PSS中位数；原始总PSS保留。初始化包含模型创建。'
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def prepare_msl(repo, config, build, task, cache):
    archive = download(build, cache, require_cached='package_lock' in config)
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
               '-lz', '-ldl', '-pthread', '-o', str(probe)]
    run_command(command, task / 'compile.log')
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


def completed_device_key(device, safe):
    """Identity stored in the success marker.

    The five fixed tasks keep the whole device record, including their
    configured port. A safe task's host port is chosen per run, so the marker
    uses the stable serial, OS, pool, and SoC instead.
    """
    if safe:
        return digest({key: device[key] for key in ('serial', 'os_version', 'pool', 'soc')})
    return digest(device)


def deploy_files(env, config, task, probe, regenerated, transport):
    """Push the probe and, for a regenerated model, the new package.

    transport=None keeps the official br push used by the existing tasks.
    A safe session never falls back to that CLI, including after a refusal,
    a timeout, or a bad sandbox hash.
    """
    if transport is not None:
        transport.probe()
        transport.push_host(probe, task / 'push.log')
        if regenerated:
            deployed = task / sandbox_basename(env['artifacts']['model']['device_path'])
            os.link(env['artifacts']['model']['host_path'], deployed)
            transport.push_host(deployed, task / 'push-model.log')
        return
    prefix = ['python3', '-m', 'binrunner', '-t', env['device']['serial'], '-p', env['device']['port']]
    ensure_forward(env, config.get('binrunner_device_port', 8888))
    run_command(prefix + ['push', str(probe)], task / 'push.log', cwd=env['binrunner'])
    if regenerated:
        # BinRunner push defaults to basename; match the locked device path exactly.
        deployed = task / Path(env['artifacts']['model']['device_path']).name
        os.link(env['artifacts']['model']['host_path'], deployed)
        push_with_resume(prefix + ['push', str(deployed)], task / 'push-model.log',
                         cwd=env['binrunner'],
                         size_bytes=Path(env['artifacts']['model']['host_path']).stat().st_size)


def run(repo, recipe_path, config, day, force=False):
    recipe = load(recipe_path)
    if requires_safe_norestart(config, recipe['id']) and 'environment' not in config:
        raise SafeTransportError(
            'mounted Qwen2.5-1.5B config has no environment; refusing br push. '
            'Install the matching file from config/deploy/.')
    env = copy.deepcopy(config['environment'])
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
        require('package_lock' not in config or backend == 'msl', 'Package locks require the MSL backend')
        build = (select_msl_build(config, recipe['id'], day, root / 'packages') if backend == 'msl'
                 else dict(recipe['build'], sha256=config['environment']['artifacts']['runtime']['sha256']))
        if build is None:
            update(status='NO_BUILD')
            return 0
        status['build_commit'] = build['commit']
        status['build_sha256'] = build['sha256']
        write_json(task / 'build.json', build)
        if 'package_lock' in config:
            write_json(task / 'package-lock.json', config['package_lock'])
        # Shared across all daily tasks: preparation/deployment must also own the device lease.
        with device_lease(root / 'leases', env['device']['serial']):
            update(stage='PREPARE')
            actual_os = device_output(env, ['param', 'get', 'const.ohos.fullname'])
            require(actual_os == env['device']['os_version'], 'Device OS differs from configured environment')
            safe = requires_safe_norestart(config, recipe['id'])
            planned_port = None
            if safe:
                # Read-only. The tuple is created only after the dedup check, under this same lease.
                planned_port = plan_host_port(
                    env, config, listing_text=read_fport_listing(env['device']['serial']),
                    listeners=listening_tcp_ports())['host_port']
                env['device']['port'] = str(planned_port)
            device_key = completed_device_key(env['device'], safe)
            source_identity = digest(source_manifest(Path(config['model_generation']['source_model']))) if backend == 'msl' and config.get('model_generation') else None
            key = digest({'source_model': source_identity, 'build': build, 'recipe': recipe, 'code': code, 'device': device_key, 'day': day, 'model_generation': config.get('model_generation')})
            marker = root / 'completed' / (key + '.json')
            if marker.exists() and not force:
                previous = json.loads(marker.read_text())
                result = json.loads(Path(previous['result']).read_text())
                write_json(repo / 'kanban/data' / (result['id'] + '.json'), result)
                update(status='SKIPPED', result_id=result['id'], stage='ARCHIVED')
                return 0
            session = (open_safe_session(env, config, task, planned_port)
                       if safe else contextlib.nullcontext(None))
            with session as transport:
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
                lock = resolve(recipe, env)
                write_new(task / 'resolved-recipe.json', lock)
                write_json(task / 'environment.json', env)
                write_json(task / 'recipe.json', recipe)
                processes = device_output(env, ['ps', '-A', '-o', 'PID,COMM'])
                require(not any(line.split()[-1].strip('[]') in {'recipe-msl', 'recipe-llama', 'edge-llama'}
                                for line in processes.splitlines() if line.split()), 'Device worker still running')
                update(stage='DEPLOY')
                with awake_device(env['device']['serial']):
                    deploy_files(env, config, task, probe, regenerated, transport)
                update(stage='MEASURE')
                output = execute(lock, transport=transport)
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
