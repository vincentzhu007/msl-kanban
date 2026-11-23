"""Regenerate an MSL from the tools/operators bundled in one master daily archive.

No source patches, PR overlays or fallback models. Each task owns its Python target,
DDK tree, source manifest, export logs and output model.
"""
import copy
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from recipe_ci.recipe import require, sha256_file, digest, validate


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        entries = {entry.filename: entry for entry in bundle.infolist()}
        links = {}
        for entry in entries.values():
            path = Path(entry.filename)
            mode = entry.external_attr >> 16
            require(not path.is_absolute() and '..' not in path.parts, 'Unsafe DDK zip entry')
            if stat.S_ISLNK(mode):
                target = bundle.read(entry).decode()
                sibling = (path.parent / target).as_posix()
                # Official simulator aliases point to a regular library in the same directory.
                require(Path(target).name == target and target not in ('.', '..') and sibling in entries
                        and stat.S_ISREG(entries[sibling].external_attr >> 16), 'Unsafe DDK zip symlink')
                links[entry.filename] = target
        for entry in entries.values():
            if entry.filename in links:
                continue
            bundle.extract(entry, destination)
            if not entry.is_dir():
                mode = entry.external_attr >> 16
                (destination / entry.filename).chmod(0o755 if mode & 0o111 else 0o644)
        for name, target in links.items():
            (destination / name).symlink_to(target)


def restore_ddk_header_link(ddk):
    """Match ms-pipeline install-ddk.sh: restore the vendor API library alias.

    DDK 6.1.1.0 materializes tikcfw/lib in its zip, breaking relative includes.
    Keep that original directory as evidence; no daily component is modified.
    """
    root = ddk / 'tools/tools_ascendc/include/tikcpp'
    link = root / 'tikcfw/lib'
    target = root / 'api/lib'
    require(target.is_dir(), 'DDK API library headers are missing')
    if link.is_symlink():
        require(link.resolve() == target.resolve(), 'Unexpected DDK header symlink')
    else:
        require(link.is_dir(), 'DDK tikcfw library headers are missing')
        backup = link.with_name('lib.ddk-6.1.1.0-materialized.bak')
        require(not backup.exists(), 'DDK header backup already exists')
        link.rename(backup)
        link.symlink_to('../api/lib', target_is_directory=True)
    require((link / 'std/tuple.h').resolve().parent.joinpath('../../impl/std/tuple/tuple_impl.h').is_file(),
            'DDK tuple implementation is missing after restoring header link')


def source_manifest(source):
    require(source.is_dir(), 'Source model directory is unavailable')
    files = sorted(p for p in source.rglob('*') if p.is_file())
    require(any(p.name == 'config.json' for p in files), 'Missing source model config')
    require(any(p.suffix == '.safetensors' for p in files), 'Missing source model weights')
    return {p.relative_to(source).as_posix(): sha256_file(p) for p in files
            if '.cache' not in p.relative_to(source).parts}


UNIX_SOCKET_BUDGET = 107
LISTENER_SUFFIX = '/listener-XXXXXXXX'
EXPORT_ENV_KEYS = frozenset({'tmpdir_root', 'tmpdir_prefix', 'tmpdir_minimum_free_bytes', 'prepend_path'})


def listener_path_length(tmpdir):
    return len(tmpdir) + len(LISTENER_SUFFIX)


def wrap_export_command(script, inner, managed=None):
    """Source the DDK env. Re-apply a short TMPDIR and PATH only when requested.

    set_ascendc_env.sh can replace PATH. The five tasks keep the original
    command. The 1.5B tasks pass managed TMPDIR and bisheng directories.
    """
    script = str(script)
    if not managed:
        return ['bash', '-c', 'source "$1"; shift; exec "$@"', 'daily-ddk-env', script, *inner]
    tmpdir = managed['tmpdir']
    prepend = os.pathsep.join(managed['prepend_path'])
    return [
        'bash', '-c',
        'source "$1"; export TMPDIR="$2"; export TMP="$2"; export TEMP="$2"; '
        'export PATH="$3${PATH:+:}$PATH"; shift 3; exec "$@"',
        'daily-ddk-env', script, tmpdir, prepend, *inner,
    ]


class ManagedExportEnv:
    def __init__(self, tmpdir, prepend_path):
        self.tmpdir = tmpdir
        self.prepend_path = list(prepend_path)

    def apply(self, env):
        env = dict(env)
        env['TMPDIR'] = env['TMP'] = env['TEMP'] = self.tmpdir
        env['PATH'] = os.pathsep.join([*self.prepend_path, env.get('PATH', '')])
        return env

    def cleanup(self):
        path = Path(self.tmpdir)
        if path.is_symlink() or not self.tmpdir.startswith('/tmp/'):
            return
        prefix = '/tmp/' + getattr(self, 'prefix', 'e15.')
        if self.tmpdir.startswith(prefix) and path.is_dir():
            shutil.rmtree(self.tmpdir, ignore_errors=True)


def prepare_export_environment(settings):
    """Short TMPDIR and bisheng PATH for a task that opts in. Others stay unchanged."""
    extra = settings.get('export_environment')
    if not extra:
        return None
    if not isinstance(extra, dict) or set(extra) - EXPORT_ENV_KEYS:
        raise ValueError('export_environment has unknown or invalid fields')
    root = extra.get('tmpdir_root', '/tmp')
    prefix = extra.get('tmpdir_prefix', 'e15.')
    if root != '/tmp' or not re.fullmatch(r'[A-Za-z0-9.]{1,8}', prefix):
        raise ValueError('export TMPDIR must be a short unique directory under /tmp')
    minimum = extra.get('tmpdir_minimum_free_bytes', 0)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError('tmpdir free-byte floor must be a non-negative int')
    if shutil.disk_usage(root).free < minimum:
        raise RuntimeError('insufficient free space on /tmp for daily export')
    prepend = extra.get('prepend_path') or []
    if not isinstance(prepend, list) or not prepend or not all(
            isinstance(item, str) and item.startswith('/') and '..' not in Path(item).parts for item in prepend):
        raise ValueError('prepend_path must be absolute directories')
    tmpdir = tempfile.mkdtemp(prefix=prefix, dir=root)
    try:
        if not tmpdir.startswith('/tmp/' + prefix) or Path(tmpdir).is_symlink():
            raise RuntimeError('mkdtemp returned an unexpected TMPDIR')
        if listener_path_length(tmpdir) >= UNIX_SOCKET_BUDGET:
            raise RuntimeError('TMPDIR still makes the AF_UNIX listener path too long')
        env_path = os.pathsep.join([*prepend, os.environ.get('PATH', '')])
        if shutil.which('bisheng', path=env_path) is None:
            raise RuntimeError('bisheng is not executable on the export PATH')
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    managed = ManagedExportEnv(tmpdir, prepend)
    managed.prefix = prefix
    return managed


def run_export(command, *, env, task, timeout, poll_seconds=5):
    """Bound the whole compiler process group; fail on confirmed missing-header errors."""
    log = task / 'export.log'
    with log.open('w') as stream:
        stream.write(json.dumps(command) + '\n'); stream.flush()
        process = subprocess.Popen(command, env=env, cwd=task, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        start = time.monotonic()
        offset, tail, failed_op, missing_header = 0, '', False, False
        try:
            while process.poll() is None:
                with log.open(errors='replace') as reader:
                    reader.seek(offset)
                    while chunk := reader.read(65536):
                        text = tail + chunk
                        failed_op |= 'single op compile failed' in text
                        missing_header |= bool(re.search(r"fatal error: [^\n]+ file not found", text))
                        tail = text[-4096:]
                    offset = reader.tell()
                if failed_op and missing_header:
                    raise RuntimeError('DDK operator compilation failed: missing header; see export.log')
                if time.monotonic() - start > timeout:
                    raise TimeoutError('Daily model export exceeded configured timeout')
                time.sleep(poll_seconds)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise


def export_model(repo, recipe, env, config, task, build, run_command, write_json):
    settings = config['model_generation']
    require(settings['mode'] == 'master_daily', 'Unsupported model generation mode')
    source = Path(settings['source_model'])
    manifest = source_manifest(source)
    write_json(task / 'source-model-manifest.json', manifest)
    require(shutil.disk_usage(task).free >= settings.get('minimum_free_bytes', 12 * 1024**3),
            'Insufficient free space for daily model export')
    package = task / 'package'
    def one(pattern):
        paths = list(package.glob(pattern))
        require(len(paths) == 1, 'Expected one daily component: ' + pattern)
        return paths[0]
    exporter = one('*/tool/mslite_llm-*.whl')
    plugin = one('*/tool/ascendc_ops/mslite_llm_ops-*.whl')
    operators = one('*/tool/ascendc_ops/*.run')
    components = {name: {'filename': p.name, 'sha256': sha256_file(p)}
                  for name, p in [('exporter', exporter), ('operator_plugin', plugin), ('operators', operators)]}
    # Upstream archive does not expose an internal Git SHA. Hash the actual shipped components.
    write_json(task / 'daily-components.json', {'archive': build, 'components': components,
               'policy': 'Unmodified exporter and operators shipped together in selected master daily',
               'mslite_internal_commit': None})
    ddk = task / 'ddk'
    staging = task / 'ddk-source'
    staging.mkdir()
    ddk_packages = Path(settings['ddk_packages'])
    target = recipe['device_pool'].lower()
    tools_zip = ddk_packages / 'DDK-tools-next-6.1.1.0.zip'
    platform_zip = ddk_packages / (target + '-plugin-next-6.1.1.0.zip')
    write_json(task / 'ddk-packages.json', {p.name: sha256_file(p) for p in [tools_zip, platform_zip]})
    extract_zip(tools_zip, staging)
    extract_zip(platform_zip, staging)
    shutil.move(str(staging / 'DDK-tools-next-6.1.1.0'), ddk)
    restore_ddk_header_link(ddk)
    write_json(task / 'ddk-environment.json', {
        'header_link': 'tikcfw/lib -> ../api/lib',
        'reference': 'ms-pipeline 8803de62b2298b13a6c5bb162131cfe1aae38f9b install-ddk.sh',
        'daily_components_modified': False})
    platform = ddk / 'tools/platform' / target
    platform.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging / 'image/ddk_platform_plugin' / target, platform, dirs_exist_ok=True)
    run_command(['env', 'PIP_NO_INDEX=1', 'PIP_NO_DEPS=1', 'bash', '-c', 'source "$1"',
                 'daily-ddk-install', str(ddk / 'tools/tools_ascendc/install.sh')],
                task / 'install-ddk.log', timeout=300)
    python = settings.get('python', '/usr/local/bin/python3')
    python_target = task / 'python'
    run_command([python, '-m', 'pip', 'install', '--no-index', '--no-deps', '--target', str(python_target),
                 str(exporter), str(plugin)], task / 'install-tools.log', timeout=180)
    run_command(['sh', str(operators), '--quiet', '--', '--prefix', str(ddk)],
                task / 'install-operators.log', timeout=180)
    output = task / 'model.msl'
    token_evidence = task / 'tokenizer-verification.json'
    # A clean module search path prevents picking up earlier PR export adapters.
    export_env = dict(os.environ, PYTHONPATH=str(python_target), PYTHONNOUSERSITE='1',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', DDK_PATH=str(ddk),
                      LD_LIBRARY_PATH=':'.join(str(p) for p in [platform/'lib64',
                          platform/'customize/op_impl/ai_core/tbe/op_tiling', ddk/'tools/tools_omg/master/lib64']))
    command = [python, str(repo / 'scripts/daily_ci/export_entry.py'), '--python-target', str(python_target),
               '--evidence', str(token_evidence), '--input-tokens', str(recipe['workload']['input_tokens']),
               '--model', str(source), '--output', str(output), '--target', target,
               '--quant-type', settings['quant_type'], '--max-length', str(recipe['workload']['context_tokens']),
               '--chunk-size', str(settings.get('chunk_size', 64)), '--keep-artifacts']
    managed = prepare_export_environment(settings)
    if managed is not None:
        export_env = managed.apply(export_env)
        write_json(task / 'export-environment.json', {
            'tmpdir': managed.tmpdir,
            'listener_path_length': listener_path_length(managed.tmpdir),
            'prepend_path': managed.prepend_path,
            'note': 'TMPDIR and PATH are re-applied after set_ascendc_env.sh for this task only.'})
    command = wrap_export_command(
        ddk / 'tools/tools_ascendc/set_ascendc_env.sh', command,
        None if managed is None else {'tmpdir': managed.tmpdir, 'prepend_path': managed.prepend_path})
    try:
        run_export(command, env=export_env, task=task, timeout=settings.get('timeout_seconds', 5400))
    finally:
        if managed is not None:
            managed.cleanup()
    require(source_manifest(source) == manifest, 'Source model changed during export')
    require(output.is_file() and output.stat().st_size > 24, 'Exporter did not produce a model')
    with output.open('rb') as stream:
        require(stream.read(4) == b'.MSL', 'Invalid exported model magic')
    evidence = json.loads(token_evidence.read_text())
    require(evidence['input_tokens'] == recipe['workload']['input_tokens'], 'Tokenizer input count mismatch')
    result = copy.deepcopy(recipe)
    checksum = sha256_file(output)
    result['model'].update(sha256=checksum, bytes=output.stat().st_size,
                          quantization={'format': settings['quant_type']},
                          provenance={'source_manifest_sha256': digest(manifest), 'daily_components': components,
                                      'generation': 'master_daily'})
    result['workload']['input_verification'] = {'model_sha256': checksum, 'tokens': evidence['input_tokens'],
                                              'evidence': json.dumps(evidence, sort_keys=True)}
    result['build'].pop('components', None)  # Never carry old PR identities into a fresh daily model.
    validate(result)
    env['artifacts']['model'] = {'host_path': str(output), 'device_path': '@/bin/daily-' + recipe['id'] + '.msl',
                                 'sha256': checksum}
    write_json(task / 'generated-model.json', {'sha256': checksum, 'bytes': output.stat().st_size,
               'source_manifest_sha256': digest(manifest), 'daily_components': components, 'tokenizer': evidence})
    return result, components
