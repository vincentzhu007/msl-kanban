"""Validate and append operator measurements to the kanban."""
import argparse
from datetime import date
import gzip
import hashlib
import json
import math
import re
from pathlib import Path
from shutil import copyfile
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parents[1] / 'kanban' / 'operator-data'
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
STATS = ('hot-samples-median', 'round-medians-median')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write((json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode())
    try:
        tmp.chmod(0o644)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def relative_file(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file(), f'附件文件无效 {name}')
    return path


def validate(result):
    require(result['schema_version'] == 1, '未知结果版本')
    for key in ('id', 'operator', 'platform'):
        require(ID.fullmatch(result[key]), f'{key} 格式无效')
    require(date.fromisoformat(result['date']).isoformat() == result['date'], '日期须为 YYYY-MM-DD')
    if result.get('commit'):
        require(re.fullmatch(r'[0-9a-f]{40}', result['commit']), '需要被测源码完整提交号')
    else:
        require(re.fullmatch(r'[0-9a-f]{64}', result['source_sha256']), '需要源码快照 SHA-256')
    require(result['statistic'] in STATS, '未知统计口径')
    for key in ('device', 'system', 'mode', 'protocol'):
        require(isinstance(result[key], str) and result[key].strip(), f'{key} 不能为空')
    case_ids = set()
    require(result['cases'], '没有测量规格')
    for case in result['cases']:
        require(ID.fullmatch(case['id']) and case['id'] not in case_ids, '规格 ID 无效或重复')
        case_ids.add(case['id'])
        require(case['label'] and case['group'] and isinstance(case['spec'], dict) and case['spec'], '缺少规格描述')
        require(case['runs'], '规格没有任何实测')
        rounds = set()
        for run in case['runs']:
            key = (run.get('phase'), run['round'])
            require(key not in rounds and type(run['round']) is int and run['round'] > 0, '轮次无效或重复')
            rounds.add(key)
            require(type(run['warmup']) is int and run['warmup'] >= 0 and run['hot'], '采样为空或预热次数无效')
            for stamp, sdk, wall in run['hot']:
                require(re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,9})?', stamp),
                        '采样时间无效')
                require(all(value is None or type(value) in (int, float) and math.isfinite(value) and value > 0
                            for value in (sdk, wall)) and (sdk is not None or wall is not None), '无效耗时样本')
    simulation_ids = set()
    for simulation in result.get('simulations', []):
        require(ID.fullmatch(simulation['id']) and simulation['id'] not in simulation_ids, '仿真 ID 无效或重复')
        simulation_ids.add(simulation['id'])
        require(simulation['label'] and simulation['spec'] and simulation['trace'], '缺少独立仿真规格')
    for trace in traces(result):
        require(ID.fullmatch(trace['platform']) and trace['scope'] in ('full', 'prefix')
                and type(trace['cycles']) is int and trace['cycles'] > 0, '无效仿真规格')


def traces(result):
    for item in [*result['cases'], *result.get('simulations', [])]:
        if item.get('trace'):
            yield item['trace']


def stage_trace(entry, source, attachments):
    path = relative_file(source, entry['file'])
    payload = path.read_bytes()
    # Imported trace assets are content addressed and can be shared across runs.
    sha = hashlib.sha256(payload).hexdigest()
    suffix = '.json.gz' if payload.startswith(b'\x1f\x8b') else '.json'
    if sha not in attachments:
        content = json.loads(gzip.decompress(payload) if suffix == '.json.gz' else payload)
        require(isinstance(content, (dict, list)), f'无效 Chrome Trace JSON {path.name}')
        attachments[sha] = path
    entry['file'] = f'traces/{sha}{suffix}'
    entry['sha256'] = sha


def import_results(inputs, destination):
    catalog_path = destination / 'catalog.json'
    catalog = read(catalog_path)
    require(catalog['schema_version'] == 1, '未知索引版本')
    additions = []
    attachments = {}
    for result, source in inputs:
        validate(result)
        operator, platform, run_id = (result[k] for k in ('operator', 'platform', 'id'))
        for trace in traces(result):
            stage_trace(trace, source, attachments)
            for variant in ('lifecycle', 'instructions'):
                if trace.get(variant):
                    stage_trace(trace[variant], source, attachments)
        record = f'runs/{operator}/{platform}/{run_id}.json'
        target = destination / record
        records = catalog['operators'].setdefault(operator, {}).setdefault(platform, [])
        if target.exists():
            require(read(target) == result, f'已有不同结果使用同一运行 ID {run_id}')
        else:
            require(all(path != target for path, _ in additions), f'重复运行 ID {run_id}')
            additions.append((target, result))
        if record not in records:
            records.append(record)
        catalog['platforms'].setdefault(platform, platform)

    for sha, path in attachments.items():
        with path.open('rb') as stream:
            compressed = stream.read(2) == b'\x1f\x8b'
        suffix = '.json.gz' if compressed else '.json'
        target = destination / 'traces' / (sha + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            require(hashlib.sha256(target.read_bytes()).hexdigest() == sha, f'已有流水校验失败 {target.name}')
        else:
            copyfile(path, target)
    for target, result in additions:
        write(target, result)
    write(catalog_path, catalog)
    print(f'新增 {len(additions)} 条运行记录')


def legacy_results(board):
    for relative in read(board / 'data/catalog.json')['campaigns']:
        result = read(relative_file(board, relative))
        result.pop('comparison', None)
        platform = result['platform'].lower().replace(' ', '')
        result.update(schema_version=1, platform=platform, protocol='S8S8 历史采样')
        # Both labels refer to the same device in the legacy 9030 archive.
        if platform == 'kirin9030' and result['device'] == 'SGT-AL00 · 9030 设备 3001':
            result['device'] = 'Mate 80 Pro · SGT-AL00'
        result.setdefault('statistic', 'round-medians-median')
        result['cases'] = [case for case in result['cases'] if case['group'] != 'UT']
        for case in result['cases']:
            case['spec'] = {'dimensions': dict(zip(('M', 'K', 'N'), case.pop('shape'), strict=True))}
            if case.get('trace'):
                case['trace']['platform'] = platform
        if result['cases']:
            yield result, board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    migrate = commands.add_parser('migrate-s8s8', help='导入旧看板的已归档结果')
    migrate.add_argument('board', type=Path)
    append = commands.add_parser('import', help='导入统一格式的评测结果')
    append.add_argument('results', type=Path, nargs='+')
    args = parser.parse_args()
    try:
        inputs = (legacy_results(args.board) if args.command == 'migrate-s8s8'
                  else ((read(path), path.parent) for path in args.results))
        import_results(inputs, args.output)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'导入失败：{error}\n')


if __name__ == '__main__':
    main()
