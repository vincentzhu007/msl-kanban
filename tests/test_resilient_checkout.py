"""Checkout must succeed offline when the commit is already on disk."""
import base64
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/ci/resilient_checkout.sh'
REAL_GIT = shutil.which('git')


class ResilientCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = self.root / 'origin.git'
        self.workspace = self.root / 'work'
        self.home = self.root / 'home'
        self.home.mkdir()
        self.wrapper_log = self.root / 'git-wrapper.log'
        self.seed = self.root / 'seed'
        self._git(None, ['init', '-b', 'main', str(self.seed)])
        self._write_commit('README', 'version-1\n', 'v1')
        self._git(self.seed, ['clone', '--bare', str(self.seed), str(self.origin)])
        self._git(None, ['clone', str(self.origin), str(self.workspace)])
        self.tip = self._rev_parse(self.origin, 'HEAD')

    def test_skips_fetch_when_commit_tree_is_already_complete(self):
        shutil.rmtree(self.origin)
        (self.workspace / 'README').write_text('dirty\n')
        (self.workspace / 'leftover.txt').write_text('remove me\n')
        result = self.checkout(self.tip)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipping fetch', result.stdout)
        self.assertNotIn('Fetching ', result.stdout)
        self.assertEqual(self._rev_parse(self.workspace, 'HEAD'), self.tip)
        self.assertEqual((self.workspace / 'README').read_text(), 'version-1\n')
        self.assertFalse((self.workspace / 'leftover.txt').exists())
        self.assertEqual(self._git_out(self.workspace, ['config', '--local', '--get', 'http.version']), 'HTTP/1.1')
        self.assertEqual(self._git_out(self.workspace, ['config', '--local', '--get', 'gc.auto']), '0')

    def test_shallow_tip_does_not_need_parents_or_network(self):
        self._write_commit('README', 'version-2\n', 'v2')
        self._git(self.seed, ['push', str(self.origin), 'main'])
        shallow = self.root / 'shallow'
        self._git(None, ['clone', '--depth', '1', 'file://' + str(self.origin), str(shallow)])
        tip = self._rev_parse(shallow, 'HEAD')
        parent = self._git_out(self.origin, ['rev-parse', 'HEAD~1'])
        missing_parent = subprocess.run(
            [REAL_GIT, '-C', str(shallow), 'cat-file', '-e', parent],
            capture_output=True, check=False)
        self.assertNotEqual(missing_parent.returncode, 0)
        remote = self._git_out(shallow, ['config', '--local', '--get', 'remote.origin.url'])
        shutil.rmtree(self.origin)
        result = self.checkout(tip, workspace=shallow, url=remote)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipping fetch', result.stdout)
        self.assertEqual((shallow / 'README').read_text(), 'version-2\n')

    def test_fetches_missing_commit_then_skips_on_the_next_run(self):
        self._write_commit('README', 'version-2\n', 'v2')
        self._git(self.seed, ['push', str(self.origin), 'main'])
        new = self._rev_parse(self.origin, 'HEAD')
        self.install_wrapper(fail_fetches=0)
        first = self.checkout(new, token='ghp_testtokenvalueShouldNotLeak99')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('not complete locally', first.stdout)
        self.assertIn('Checked out ' + new, first.stdout)
        self.assertEqual((self.workspace / 'README').read_text(), 'version-2\n')
        log = self.wrapper_log.read_text()
        fetches = [line for line in log.splitlines() if line.startswith('ARGV ')]
        self.assertEqual(len(fetches), 1)
        self.assertIn('--depth=1', fetches[0])
        self.assertIn('protocol.version=2', fetches[0])
        self.assertIn('+' + new + ':refs/remotes/origin/main', fetches[0])
        self.assertNotIn('AUTHORIZATION', fetches[0])
        self.assertIn('http.version=HTTP/1.1', log)
        self.assertIn('lowSpeedLimit=1000', log)
        self.assertIn('lowSpeedTime=60', log)
        self.assertIn('header=present', log)
        config = (self.workspace / '.git/config').read_text()
        self.assertNotIn('ghp_testtokenvalueShouldNotLeak99', config)
        self.assertNotIn('extraheader', config.lower())
        self.assertNotIn('AUTHORIZATION', config)
        blob = base64.b64encode(b'x-access-token:ghp_testtokenvalueShouldNotLeak99').decode()
        combined = first.stdout + first.stderr
        self.assertNotIn('ghp_testtokenvalueShouldNotLeak99', combined)
        self.assertNotIn(blob, combined)
        self.assertNotIn('ghp_testtokenvalueShouldNotLeak99', self.wrapper_log.read_text())
        second = self.checkout(new, token='ghp_testtokenvalueShouldNotLeak99')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('Skipping fetch', second.stdout)
        fetches = [line for line in self.wrapper_log.read_text().splitlines() if line.startswith('ARGV ')]
        self.assertEqual(len(fetches), 1)

    def test_missing_blob_is_fetched_instead_of_skipping(self):
        self.delete_blob(self.workspace, 'HEAD:README')
        result = self.checkout(self.tip)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('not complete locally', result.stdout)
        self.assertEqual((self.workspace / 'README').read_text(), 'version-1\n')

    def test_retries_transient_fetch_errors_then_checks_out(self):
        self._write_commit('README', 'version-2\n', 'v2')
        self._git(self.seed, ['push', str(self.origin), 'main'])
        new = self._rev_parse(self.origin, 'HEAD')
        self.install_wrapper(fail_fetches=2, fail_message='fatal: unable to access \'https://github.com/example/repo/\': Failed to connect to github.com port 443 after 130000 ms: Connection timed out')
        result = self.checkout(new, max_attempts=4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.workspace / 'README').read_text(), 'version-2\n')
        self.assertEqual(result.stdout.count('Fetch failed; waiting'), 2)
        self.assertIn('attempt 3/4', result.stdout)
        argv = [line for line in self.wrapper_log.read_text().splitlines() if line.startswith('ARGV ')]
        self.assertEqual(len(argv), 3)

    def test_authentication_failure_is_not_retried(self):
        missing = '0123456789abcdef0123456789abcdef01234567'
        self.install_wrapper(fail_fetches=5, fail_message='fatal: Authentication failed for \'https://github.com/example/repo/\'')
        result = self.checkout(missing, max_attempts=5, token='not-a-real-token')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not retrying', result.stderr)
        argv = [line for line in self.wrapper_log.read_text().splitlines() if line.startswith('ARGV ')]
        self.assertEqual(len(argv), 1)
        config = (self.workspace / '.git/config').read_text()
        self.assertNotIn('not-a-real-token', config)

    def test_gives_up_after_the_attempt_budget(self):
        missing = 'abcdefabcdefabcdefabcdefabcdefabcdefabcd'
        self.install_wrapper(fail_fetches=9, fail_message='fatal: HTTP/2 stream 1 was not closed cleanly before end of the underlying stream')
        result = self.checkout(missing, max_attempts=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('after 3 attempts', result.stderr)
        argv = [line for line in self.wrapper_log.read_text().splitlines() if line.startswith('ARGV ')]
        self.assertEqual(len(argv), 3)

    def test_attempt_timeout_kills_a_hung_fetch(self):
        missing = 'fedcba9876543210fedcba9876543210fedcba98'
        self.install_wrapper(hang_seconds=30)
        result = self.checkout(missing, max_attempts=1, attempt_timeout=1)
        self.assertNotEqual(result.returncode, 0)
        log = self.wrapper_log.read_text()
        self.assertIn('start-hang', log)
        self.assertNotIn('finished-hang', log)

    def test_strips_embedded_credentials_without_fetching(self):
        secret = 'x-access-token:SUPER_SECRET_EMBEDDED_TOKEN'
        self._git(self.workspace, ['remote', 'set-url', 'origin', 'https://' + secret + '@github.com/example/repo.git'])
        shutil.rmtree(self.origin)
        result = self.checkout(self.tip, repository='example/repo', allow_override=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipping fetch', result.stdout)
        config = (self.workspace / '.git/config').read_text()
        self.assertNotIn('SUPER_SECRET_EMBEDDED_TOKEN', config)
        self.assertNotIn('@', self._git_out(self.workspace, ['config', '--local', '--get', 'remote.origin.url']))
        self.assertEqual(
            self._git_out(self.workspace, ['config', '--local', '--get', 'remote.origin.url']),
            'https://github.com/example/repo')
        combined = result.stdout + result.stderr
        self.assertNotIn('SUPER_SECRET_EMBEDDED_TOKEN', combined)

    def test_scrubs_stale_extraheader_on_the_skip_path(self):
        self._git(self.workspace, ['config', '--local', 'http.https://github.com/.extraheader', 'AUTHORIZATION: basic STALESECRETVALUE'])
        shutil.rmtree(self.origin)
        result = self.checkout(self.tip)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.workspace / '.git/config').read_text()
        self.assertNotIn('STALESECRETVALUE', config)
        self.assertNotIn('extraheader', config.lower())

    def test_rejects_unsafe_sha_without_fetching_or_touching_files(self):
        self.install_wrapper(fail_fetches=0)
        (self.workspace / 'README').write_text('keep\n')
        result = self.checkout('0123456789abcdef0123456789abcdef01234567;touch pwned')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.wrapper_log.exists())
        self.assertEqual((self.workspace / 'README').read_text(), 'keep\n')
        self.assertFalse((self.workspace / 'pwned').exists())

    def test_reinitializes_when_origin_is_a_different_repository(self):
        other = self.root / 'other.git'
        other_seed = self.root / 'other-seed'
        self._git(None, ['init', '-b', 'main', str(other_seed)])
        (other_seed / 'README').write_text('other-repo\n')
        self._git(other_seed, ['add', 'README'])
        self._commit(other_seed, 'other')
        self._git(other_seed, ['clone', '--bare', str(other_seed), str(other)])
        other_sha = self._rev_parse(other, 'HEAD')
        result = self.checkout(other_sha, url=str(other))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('reinitializing', result.stdout)
        self.assertEqual((self.workspace / 'README').read_text(), 'other-repo\n')
        self.assertEqual(self._rev_parse(self.workspace, 'HEAD'), other_sha)

    def test_workflow_inlines_the_script_and_no_workflow_uses_actions_checkout(self):
        script = SCRIPT.read_text()
        workflow_dir = ROOT / '.github/workflows'
        workflows = sorted(workflow_dir.glob('*.yml'))
        self.assertGreaterEqual(len(workflows), 2)
        daily = (workflow_dir / 'daily-qwen25-9020.yml').read_text()
        begin = '          # BEGIN scripts/ci/resilient_checkout.sh\n'
        end = '          # END scripts/ci/resilient_checkout.sh\n'
        start = daily.index(begin) + len(begin)
        stop = daily.index(end)
        extracted = []
        for line in daily[start:stop].splitlines(keepends=True):
            if line.strip() == '':
                extracted.append('\n')
                continue
            self.assertTrue(line.startswith('          '), repr(line))
            extracted.append(line[10:])
        self.assertEqual(''.join(extracted), script)
        for path in workflows:
            self.assertNotRegex(path.read_text(), r'uses:\s*actions/checkout', path.name)
        self.assertIn('CHECKOUT_MAX_ATTEMPTS: "8"', daily)
        self.assertIn('CHECKOUT_ATTEMPT_TIMEOUT: "150"', daily)
        self.assertIn('CHECKOUT_ALLOW_URL_OVERRIDE: "0"', daily)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", daily)

    def checkout(self, sha, workspace=None, token='', repository='example/repo', ref='main',
                 max_attempts=8, attempt_timeout=30, allow_override=True, url=None):
        workspace = workspace or self.workspace
        env = {
            'PATH': os.environ['PATH'],
            'HOME': str(self.home),
            'TMPDIR': str(self.root),
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_CONFIG_SYSTEM': '/dev/null',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': 'Test',
            'GIT_AUTHOR_EMAIL': 'test@example.com',
            'GIT_COMMITTER_NAME': 'Test',
            'GIT_COMMITTER_EMAIL': 'test@example.com',
            'GIT_TERMINAL_PROMPT': '0',
            'CHECKOUT_SHA': sha,
            'CHECKOUT_REPOSITORY': repository,
            'CHECKOUT_REF_NAME': ref,
            'CHECKOUT_MAX_ATTEMPTS': str(max_attempts),
            'CHECKOUT_ATTEMPT_TIMEOUT': str(attempt_timeout),
            'CHECKOUT_RETRY_SCALE': '0',
            'GITHUB_WORKSPACE': str(workspace),
            'GITHUB_TOKEN': token,
        }
        if allow_override:
            env['CHECKOUT_ALLOW_URL_OVERRIDE'] = '1'
            env['CHECKOUT_URL'] = str(url or self.origin)
        if self.wrapper_log.parent.exists() and (self.root / 'bin' / 'git').exists():
            env['PATH'] = str(self.root / 'bin') + os.pathsep + env['PATH']
            env['GIT_WRAPPER_LOG'] = str(self.wrapper_log)
            env['REAL_GIT'] = REAL_GIT
        for key in ('FAIL_FETCHES', 'FAIL_MESSAGE', 'HANG_FETCH'):
            if key in getattr(self, '_wrapper_env', {}):
                env[key] = self._wrapper_env[key]
        completed = subprocess.run(
            ['bash', str(SCRIPT)],
            cwd=str(self.root / 'not-the-workspace') if (self.root / 'not-the-workspace').exists() else str(self.home),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return completed

    def install_wrapper(self, fail_fetches=0, fail_message='', hang_seconds=0):
        bindir = self.root / 'bin'
        bindir.mkdir(exist_ok=True)
        wrapper = bindir / 'git'
        wrapper.write_text(textwrap.dedent(r'''
            #!/bin/bash
            set -euo pipefail
            log="${GIT_WRAPPER_LOG:?}"
            real="${REAL_GIT:?}"
            if [[ " $* " == *" fetch "* ]]; then
              {
                printf 'ARGV'
                printf ' %q' "$@"
                printf '\n'
                printf 'http.version=%s\n' "${GIT_CONFIG_VALUE_0:-}"
                printf 'lowSpeedLimit=%s\n' "${GIT_CONFIG_VALUE_1:-}"
                printf 'lowSpeedTime=%s\n' "${GIT_CONFIG_VALUE_2:-}"
                if [[ "${GIT_CONFIG_VALUE_3:-}" == AUTHORIZATION:\ basic\ * ]]; then
                  printf 'header=present\n'
                else
                  printf 'header=absent\n'
                fi
              } >> "$log"
              if [[ -n "${HANG_FETCH:-}" ]]; then
                echo start-hang >> "$log"
                sleep "$HANG_FETCH"
                echo finished-hang >> "$log"
                exit 1
              fi
              n=$(grep -c '^ARGV ' "$log")
              if [[ "$n" -le "${FAIL_FETCHES:-0}" ]]; then
                printf '%s\n' "${FAIL_MESSAGE:-fatal: connection timed out}" >&2
                exit 128
              fi
            fi
            exec "$real" "$@"
        ''').lstrip())
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        self._wrapper_env = {
            'FAIL_FETCHES': str(fail_fetches),
            'FAIL_MESSAGE': fail_message,
            'HANG_FETCH': str(hang_seconds) if hang_seconds else '',
        }

    def delete_blob(self, repo, rev):
        blob = self._rev_parse(repo, rev)
        pack_dir = repo / '.git/objects/pack'
        if pack_dir.exists():
            for pack in list(pack_dir.glob('*.pack')):
                with pack.open('rb') as handle:
                    subprocess.run(
                        [REAL_GIT, '-C', str(repo), 'unpack-objects'],
                        stdin=handle, check=True, capture_output=True)
                pack.unlink()
                index = pack.with_suffix('.idx')
                if index.exists():
                    index.unlink()
        loose = repo / '.git/objects' / blob[:2] / blob[2:]
        self.assertTrue(loose.exists(), 'blob was not stored loose')
        loose.unlink()
        missing = subprocess.run(
            [REAL_GIT, '-C', str(repo), 'cat-file', '-e', blob],
            capture_output=True, check=False)
        self.assertNotEqual(missing.returncode, 0)

    def _write_commit(self, name, content, message):
        (self.seed / name).write_text(content)
        self._git(self.seed, ['add', name])
        self._commit(self.seed, message)

    def _commit(self, repo, message):
        self._git(repo, ['-c', 'user.email=test@example.com', '-c', 'user.name=Test', 'commit', '-m', message])

    def _rev_parse(self, repo, rev):
        return self._git_out(repo, ['rev-parse', rev])

    def _git_out(self, repo, args):
        return self._git(repo, args, capture=True).stdout.strip()

    def _git(self, repo, args, capture=False):
        command = [REAL_GIT]
        if repo is not None and args and args[0] != '-C' and not args[0].startswith('-c') and args[0] != 'init' and args[0] != 'clone':
            command += ['-C', str(repo)]
        # init/clone are called with the path in args. Other commands use -C,
        # except when the caller already passed -c before the subcommand.
        if repo is not None and args and args[0] == '-c':
            command = [REAL_GIT, '-C', str(repo), *args]
        elif repo is not None and args and args[0] in ('init', 'clone'):
            command = [REAL_GIT, *args]
        else:
            command += args
        env = os.environ.copy()
        env['GIT_CONFIG_GLOBAL'] = '/dev/null'
        env['GIT_CONFIG_NOSYSTEM'] = '1'
        env['GIT_AUTHOR_NAME'] = 'Test'
        env['GIT_AUTHOR_EMAIL'] = 'test@example.com'
        env['GIT_COMMITTER_NAME'] = 'Test'
        env['GIT_COMMITTER_EMAIL'] = 'test@example.com'
        completed = subprocess.run(command, check=True, text=True, capture_output=True, env=env)
        return completed if capture else completed


if __name__ == '__main__':
    unittest.main()
