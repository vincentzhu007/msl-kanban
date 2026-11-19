#!/usr/bin/env python3
"""Rerun the PSS baseline contract offline.

Synthetic floors prove the narrow warning. With --pack, the script also
replays the packed 2026-11-19 measurement: the pack's own
replay_old_hardfail.py must still raise, and the workspace
summarize_recipe / public_result path must return a candidate. The pack
directory is only read. CSV output goes to a temporary copy.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

PUBLISHED_FLOOR = [76680, 85528, 89836, 89838, 89902]
BASE_COMMIT = '54a8175e747ad5c0537e393bc958608c5817e37c'
EVIDENCE_COMMIT = '257a548a28968ee2251d3e7ffcec58c8abbba391'


def rows():
    return [dict(ttft_ms=1, decode_ms=1, total_ms=2, decode_tps=1)]


def memory(floor, stable_total=500000):
    samples = [dict(stable_decode=False, fully_in_inference=False, graph_kib=0,
                    total_pss_kib=value, start_epoch_ms=i * 1000, baseline_sample=True,
                    pid=12, baseline_scope='before_model_create')
               for i, value in enumerate(floor)]
    for extra in (1, 2):
        samples.append(dict(stable_decode=True, fully_in_inference=True, graph_kib=50,
                            total_pss_kib=stable_total, start_epoch_ms=(len(floor) + extra) * 1000,
                            baseline_sample=False, pid=12, baseline_scope='before_model_create'))
    return samples


def load_commit(commit):
    source = subprocess.check_output(
        ['git', 'show', f'{commit}:scripts/bench_common/metrics.py'], cwd=ROOT)
    spec = importlib.util.spec_from_loader('metrics_base', loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, f'{commit}:metrics.py', 'exec'), module.__dict__)
    return module


def run_case(mod, floor, stable_total=500000):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            _, stats = mod.summarize(rows(), memory(floor, stable_total))
        except ValueError as exc:
            return {'outcome': 'reject', 'error': str(exc),
                    'warnings': [str(item.message) for item in caught]}
    return {
        'outcome': 'result',
        'warnings': [str(item.message) for item in caught],
        'quality': stats.get('quality'),
        'has_net': 'net_pss_kib' in stats,
        'ram_method': stats.get('ram_method'),
        'baseline': {key: stats['baseline_pss_kib'].get(key)
                     for key in ('median', 'min', 'max', 'samples', 'range_kib',
                                 'stability_limit_kib', 'accepted')},
        'observed_stable_median': stats['total_pss_kib']['stable_median'],
    }


def expect(condition, message):
    if not condition:
        raise SystemExit(message)


def synthetic(base_commit):
    from bench_common import metrics as current
    base = load_commit(base_commit)
    old = run_case(base, PUBLISHED_FLOOR)
    new = run_case(current, PUBLISHED_FLOOR)
    report = {
        'base_commit': base_commit,
        'synthetic_published_floor': PUBLISHED_FLOOR,
        'not_a_hidumper_reparse': True,
        'old': old,
        'new': new,
        'stable': run_case(current, [100, 102, 98]),
        'missing': run_case(current, [100, 102]),
        'non_finite': run_case(current, [100, 102, float('nan')]),
        'negative': run_case(current, PUBLISHED_FLOOR, stable_total=100),
    }
    expect(old['outcome'] == 'reject' and old['error'] == 'PSS baseline is unstable',
           'base commit did not reject the synthetic floor')
    warning = (new.get('quality') or {}).get('warnings', [{}])[0]
    expect(new['outcome'] == 'result' and warning.get('code') == 'pss_baseline_unstable',
           'current code did not return the unstable warning')
    expect(warning.get('net_pss_kib') == 'not_calculated', 'net was not marked not_calculated')
    expect(new['has_net'] is False and new['ram_method'] is None, 'unstable result published a net or method')
    expect(new['baseline']['median'] == 89836 and new['baseline']['samples'] == 5, 'baseline stats dropped')
    expect(new['baseline']['accepted'] is False, 'unstable baseline was marked accepted')
    expect(new['observed_stable_median'] == 500000, 'direct observation changed')
    expect(report['stable']['outcome'] == 'result' and report['stable']['quality'] is None
           and report['stable']['warnings'] == [] and report['stable']['has_net'] is True,
           'stable baseline changed')
    expect(report['missing']['outcome'] == 'reject' and 'three complete' in report['missing']['error'],
           'short baseline was accepted')
    expect(report['non_finite']['outcome'] == 'reject' and 'not finite' in report['non_finite']['error'],
           'non-finite baseline was accepted')
    expect(report['negative']['outcome'] == 'reject' and report['negative']['error'].startswith('Negative'),
           'negative net was accepted')
    return report


def sha256(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def verify_manifest(pack):
    manifest = json.loads((pack / 'MANIFEST.json').read_text())
    mismatches = []
    for item in manifest['files']:
        path = pack / item['pack_path']
        actual = sha256(path) if path.is_file() else None
        if actual != item['copy_sha256'] or actual != item['source_sha256'] or path.stat().st_size != item['bytes']:
            mismatches.append({'path': item['pack_path'], 'actual': actual, 'copy': item['copy_sha256']})
    expect(not mismatches, 'manifest hash mismatch: ' + json.dumps(mismatches))
    return {'files': len(manifest['files']), 'evidence_commit': manifest['run']['code_commit']}


def replay_pack(pack, out):
    expect((pack / 'replay' / 'replay_old_hardfail.py').is_file(), 'pack replay script missing')
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    old = subprocess.run([sys.executable, 'replay/replay_old_hardfail.py'], cwd=pack,
                         env=env, text=True, capture_output=True)
    expect(old.returncode == 0 and 'OLD_HARD_FAIL_REPRODUCED' in old.stdout,
           'packed old metrics did not reproduce the hard failure\n' + old.stdout + old.stderr)
    work = Path(tempfile.mkdtemp(prefix='pss-validate-'))
    shutil.copytree(pack / 'measurement', work / 'measurement')
    recipe = json.loads((pack / 'task-meta' / 'recipe.json').read_text())
    build = json.loads((pack / 'task-meta' / 'build.json').read_text())
    if (pack / 'task-meta' / 'generated-model.json').is_file():
        build = dict(build, model_generation='master_daily')
    from recipe_ci.recipe import require
    from recipe_ci.results import summarize_recipe
    from daily_ci.pipeline import public_result
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = summarize_recipe(recipe, work / 'measurement',
                                  run_id='offline-candidate-20261119-qwen25-05b-msl-q30-kirin9020')
    require(result['verification']['artifact_identity'], 'measurement lock did not verify device artifacts')
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    public = public_result(result, result['id'], build, code, 'offline-unpublished', None)
    text = json.dumps(public, indent=2, ensure_ascii=False, allow_nan=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + '\n')
    memory = public['memory']
    warning = memory['quality']['warnings'][0]
    expect(warning['code'] == 'pss_baseline_unstable', 'candidate lost the warning')
    expect(warning['net_pss_kib'] == 'not_calculated', 'candidate calculated net')
    expect('net_pss_kib' not in memory and 'ram_method' not in memory, 'candidate published net or method')
    expect('RAM已扣除' not in public['protocol_note'], 'public note claims the baseline was subtracted')
    expect('未计算' in public['protocol_note'], 'public note does not say net was not calculated')
    expect(memory['baseline_pss_kib']['sample_kib'] == PUBLISHED_FLOOR, 'real baseline samples differ')
    expect(memory['baseline_pss_kib']['accepted'] is False, 'real baseline marked accepted')
    expect(memory['total_pss_kib']['sampled_peak'] == 417842, 'observed peak differs from the packed readout')
    messages = [str(item.message) for item in caught]
    expect(any(message == 'PSS baseline is unstable' for message in messages), 'stderr warning missing')
    expect(any('excluded terminal sample' in message for message in messages),
           'terminal-sample warning from the real log was dropped')
    task_lock = json.loads((pack / 'task-meta' / 'resolved-recipe.json').read_text())
    expect(task_lock['device_artifacts_verified'] is False, 'task lock unexpectedly verified')
    expect(public['verification']['artifact_identity'] is True, 'candidate did not use the measurement lock')
    return {
        'old_returncode': old.returncode,
        'old_stdout': old.stdout,
        'old_stderr': old.stderr,
        'candidate': str(out),
        'candidate_sha256': sha256(out),
        'work_dir': str(work),
        'warnings': messages,
        'baseline': memory['baseline_pss_kib'],
        'total_pss_kib': memory['total_pss_kib'],
        'graph_kib': memory['graph_kib'],
        'protocol_note': public['protocol_note'],
        'producer_commit': code,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-commit', default=BASE_COMMIT)
    parser.add_argument('--pack', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    report = {'synthetic': synthetic(args.base_commit), 'evidence_commit': EVIDENCE_COMMIT}
    if args.pack:
        pack = args.pack.resolve()
        report['manifest'] = verify_manifest(pack)
        expect(report['manifest']['evidence_commit'] == EVIDENCE_COMMIT, 'pack commit differs')
        out = args.out or Path(tempfile.mkdtemp(prefix='pss-candidate-')) / 'candidate.json'
        report['pack'] = replay_pack(pack, out)
        report['manifest_after'] = verify_manifest(pack)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
