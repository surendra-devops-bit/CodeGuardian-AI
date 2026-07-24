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


def test_generate_fix_for_issue_dry_run(tmp_path, monkeypatch):
    # create a sample python file
    sample = tmp_path / 'sample.py'
    sample.write_text('a = 1\n')

    # fake SONAR_PROJECT_KEY and issue component format
    auto_ai_fix.SONAR_PROJECT_KEY = 'proj'
    issue = {'component': f'proj:{str(sample)}', 'message': 'test', 'severity': 'MAJOR', 'rule': 'py-rule', 'line': 1}

    # monkeypatch LLM to return a syntactically-correct Python change
    monkeypatch.setattr(auto_ai_fix, 'call_llm', lambda prompt: 'a = 2\n')

    # run dry-run generation
    res = auto_ai_fix.generate_fix_for_issue(issue, dry_run=True)

    assert res is True
    # original file should remain unchanged
    assert sample.read_text() == 'a = 1\n'
    # dry-run artifact should be written
    artifact = Path(f'.ai_fix_dryrun_{sample.name}.patch')
    assert artifact.exists()
    # cleanup
    artifact.unlink()
