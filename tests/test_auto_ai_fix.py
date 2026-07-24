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
