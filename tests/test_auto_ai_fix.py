import importlib.util
import subprocess
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

fake_requests = types.ModuleType('requests')
fake_requests.get = lambda *args, **kwargs: None
fake_requests.post = lambda *args, **kwargs: None
sys.modules.setdefault('requests', fake_requests)

SPEC = importlib.util.spec_from_file_location('auto_ai_fix', ROOT / 'scripts' / 'auto_ai_fix.py')
auto_ai_fix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_ai_fix)


def test_run_validation_commands_runs_build_and_test(monkeypatch):
    calls = []

    def fake_run(cmd, check=True, capture_output=False, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(auto_ai_fix, 'run', fake_run)

    result = auto_ai_fix.run_validation_commands('./gradlew build', './gradlew test')

    assert calls == [['./gradlew', 'build'], ['./gradlew', 'test']]
    assert result['build'].returncode == 0
    assert result['test'].returncode == 0


def test_create_branch_uses_auto_ai_fix_prefix(monkeypatch):
    monkeypatch.setenv('AI_FIX_BRANCH_PREFIX', 'auto-ai-fix')
    auto_ai_fix.refresh_config()

    called = []

    def fake_run(cmd, check=True, capture_output=False, env=None):
        called.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(auto_ai_fix, 'run', fake_run)

    branch_name = auto_ai_fix.create_branch()

    assert branch_name.startswith('auto-ai-fix-')
    assert called == [['git', 'checkout', '-B', branch_name]]


def test_create_pull_request_posts_to_github(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'gh-token')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    auto_ai_fix.refresh_config()

    captured = {}

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    def fake_requests_post(url, *args, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs.get('json')
        captured['headers'] = kwargs.get('headers')
        return FakeResponse({'html_url': 'https://github.com/owner/repo/pull/1'})

    monkeypatch.setattr(auto_ai_fix, 'requests_post', fake_requests_post)

    pr_url = auto_ai_fix.create_pull_request('auto-ai-fix-123')

    assert pr_url == 'https://github.com/owner/repo/pull/1'
    assert captured['url'] == 'https://api.github.com/repos/owner/repo/pulls'
    assert captured['json']['head'] == 'auto-ai-fix-123'
    assert captured['json']['base'] == 'main'
    assert captured['headers']['Authorization'] == 'token gh-token'
