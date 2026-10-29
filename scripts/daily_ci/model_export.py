"""Regenerate an MSL from the tools/operators bundled in one master daily archive.

No source patches, PR overlays or fallback models. Each task owns its Python target,
DDK tree, source manifest, export logs and output model.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

from recipe_ci.recipe import require, sha256_file, digest, validate


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            path = Path(entry.filename)
            mode = entry.external_attr >> 16
            require(not path.is_absolute() and '..' not in path.parts and not stat.S_ISLNK(mode),
                    'Unsafe DDK zip entry')
        bundle.extractall(destination)
        for entry in bundle.infolist():
            if not entry.is_dir():
                mode = entry.external_attr >> 16
                (destination / entry.filename).chmod(0o755 if mode & 0o111 else 0o644)


def source_manifest(source):
    require(source.is_dir(), 'Source model directory is unavailable')
    files = sorted(p for p in source.rglob('*') if p.is_file())
    require(any(p.name == 'config.json' for p in files), 'Missing source model config')
    require(any(p.suffix == '.safetensors' for p in files), 'Missing source model weights')
    return {p.relative_to(source).as_posix(): sha256_file(p) for p in files
            if '.cache' not in p.relative_to(source).parts}


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
    platform = ddk / 'tools/platform' / target
    platform.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging / 'image/ddk_platform_plugin' / target, platform, dirs_exist_ok=True)
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
    with (task / 'export.log').open('w') as stream:
        stream.write(json.dumps(command) + '\n'); stream.flush()
        subprocess.run(command, env=export_env, cwd=task, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=settings.get('timeout_seconds', 5400))
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
