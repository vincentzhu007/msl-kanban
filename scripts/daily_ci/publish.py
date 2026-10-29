"""Atomically publish one task's validated files via GitHub's Git Data API."""
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def task_files(root, task, run_id, attempt):
    for value in (task, run_id, attempt):
        if not re.fullmatch(r'[a-zA-Z0-9-]+', value):
            raise ValueError('Invalid task identity')
    matches = list((root / 'kanban/jobs').glob(f'*-{task}-{run_id}-{attempt}.json'))
    if len(matches) != 1:
        raise ValueError('Expected exactly one task record')
    status = json.loads(matches[0].read_text())
    paths = [matches[0]]
    if status['status'] in ('SUCCEEDED', 'SKIPPED'):
        result_id = status['result_id']
        if not re.fullmatch(r'[a-zA-Z0-9-]+', result_id):
            raise ValueError('Invalid result id')
        result_path = root / 'kanban/data' / (result_id + '.json')
        result = json.loads(result_path.read_text())
        if result['id'] != result_id or not result['verification']['artifact_identity']:
            raise ValueError('Result identity is not verified')
        paths.append(result_path)
    return {p.relative_to(root).as_posix(): p.read_text() for p in paths}


def publish(files, api, message, pause=time.sleep):
    """Rebase the tree on each retry; never force-update the branch."""
    for attempt in range(4):
        try:
            head = api('GET', '/git/ref/heads/main')['object']['sha']
            base = api('GET', '/git/commits/' + head)['tree']['sha']
            tree = api('POST', '/git/trees', {'base_tree': base, 'tree': [
                {'path': path, 'mode': '100644', 'type': 'blob', 'content': content}
                for path, content in files.items()]})['sha']
            if tree == base:
                return head
            commit = api('POST', '/git/commits', {'message': message, 'tree': tree, 'parents': [head]})['sha']
            api('PATCH', '/git/refs/heads/main', {'sha': commit, 'force': False})
            return commit
        except (HTTPError, URLError, TimeoutError) as error:
            # Ref races are retried against the new head; auth/validation errors fail immediately.
            if isinstance(error, HTTPError) and error.code not in (409, 422, 429, 500, 502, 503, 504):
                raise
            if attempt == 3:
                raise
            print('GitHub API retry:', type(error).__name__, flush=True)
            pause(5 * (attempt + 1))


def main():
    root = Path(__file__).resolve().parents[2]
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    token = os.environ['GITHUB_TOKEN']

    def api(method, path, body=None):
        request = Request('https://api.github.com/repos/' + repository + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Authorization': 'Bearer ' + token,
                                   'Accept': 'application/vnd.github+json',
                                   'Content-Type': 'application/json',
                                   'X-GitHub-Api-Version': '2022-11-28'}, method=method)
        with urlopen(request, timeout=45) as response:
            return json.load(response)

    task = os.environ['TASK']
    run_id = os.environ['GITHUB_RUN_ID']
    files = task_files(root, task, run_id, os.environ['GITHUB_RUN_ATTEMPT'])
    commit = publish(files, api, f'data: daily {task} evaluation {run_id}')
    print('Published commit:', commit, flush=True)


if __name__ == '__main__':
    main()
