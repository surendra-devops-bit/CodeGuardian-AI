import importlib.util
import json
import sys
import types
from pathlib import Path
from subprocess import CompletedProcess

ROOT = Path(__file__).resolve().parents[1]

fake_requests = types.ModuleType('requests')
fake_requests.get = lambda *args, **kwargs: None
fake_requests.post = lambda *args, **kwargs: None
sys.modules.setdefault('requests', fake_requests)

SPEC = importlib.util.spec_from_file_location('auto_ai_fix', ROOT / 'scripts' / 'auto_ai_fix.py')
auto_ai_fix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_ai_fix)


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_end_to_end_flow(tmp_path, monkeypatch):
    # Prepare source file and environment
    sample = tmp_path / 'sample.py'
    sample.write_text('a = 1\n')

    monkeypatch.setenv('SONAR_HOST_URL', 'https://sonar.example.com')
    monkeypatch.setenv('SONAR_TOKEN', 'sonar-token')
    monkeypatch.setenv('SONAR_PROJECT_KEY', 'proj')
    monkeypatch.setenv('LLM_API_KEY', 'llm-key')
    monkeypatch.setenv('GITHUB_TOKEN', 'gh-token')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('BUILD_COMMAND', 'echo build-ok')
    monkeypatch.setenv('TEST_COMMAND', 'echo test-ok')
    monkeypatch.setenv('SONAR_SCANNER_CMD', 'echo sonar-ok')
    monkeypatch.setenv('AI_FIX_BRANCH_PREFIX', 'auto-ai-fix')
    monkeypatch.setenv('TARGET_BRANCH', 'main')
    monkeypatch.setenv('EMAIL_RECIPIENTS', 'approver@example.com')
    monkeypatch.setenv('SMTP_SERVER', 'smtp.example.com')
    monkeypatch.setenv('SMTP_PORT', '587')
    monkeypatch.setenv('SMTP_USERNAME', 'user@example.com')
    monkeypatch.setenv('SMTP_PASSWORD', 'secret')

    auto_ai_fix.refresh_config()

    issues = [
        {
            'component': f'proj:{sample}',
            'message': 'Fix issue',
            'severity': 'MAJOR',
            'rule': 'py-rule',
            'line': 1,
        }
    ]
    quality_payload = {'projectStatus': {'status': 'OK'}}

    def fake_requests_get(url, *args, **kwargs):
        if 'api/issues/search' in url:
            return FakeResponse({'issues': issues})
        if 'api/qualitygates/project_status' in url:
            return FakeResponse(quality_payload)
        raise RuntimeError(f'Unexpected GET {url}')

    def fake_requests_post(url, *args, **kwargs):
        if 'api.github.com/repos' in url:
            return FakeResponse({'html_url': 'https://github.com/owner/repo/pull/1'})
        raise RuntimeError(f'Unexpected POST {url}')

    monkeypatch.setattr(auto_ai_fix, 'requests_get', fake_requests_get)
    monkeypatch.setattr(auto_ai_fix, 'requests_post', fake_requests_post)
    monkeypatch.setattr(auto_ai_fix, 'call_llm', lambda prompt: 'a = 2\n')

    captured = []

    def fake_run(cmd, check=True, capture_output=False, env=None):
        captured.append(cmd)
        if cmd[:3] == ['git', 'status', '--porcelain']:
            return CompletedProcess(cmd, 0, stdout=' M sample.py', stderr='')
        if cmd[0] == 'git' and cmd[1] in {'checkout', 'add', 'commit', 'push'}:
            return CompletedProcess(cmd, 0, stdout='', stderr='')
        return CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(auto_ai_fix, 'run', fake_run)

    class FakeSMTP:
        def __init__(self, server, port):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, message):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(auto_ai_fix, 'smtplib', types.SimpleNamespace(SMTP=FakeSMTP))

    monkeypatch.setattr(auto_ai_fix, 'parse_args', lambda argv=None: types.SimpleNamespace(dry_run=False, max_issues=1))

    # Run the full main flow
    auto_ai_fix.main()

    assert sample.read_text() == 'a = 2\n'
    audit_file = Path('.ai_fix_report.json')
    assert audit_file.exists()
    report = json.loads(audit_file.read_text(encoding='utf-8'))
    assert report['pr_url'] == 'https://github.com/owner/repo/pull/1'
    assert report['branch_name'].startswith('auto-ai-fix-')
    assert report['quality_gate'] == 'OK'
