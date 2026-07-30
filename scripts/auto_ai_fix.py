#!/usr/bin/env python3
import argparse
import ast
import functools
import json
import logging
import os
import random
import re
import shlex
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover - exercised only when requests is unavailable
    class _RequestsStub:
        @staticmethod
        def get(*args, **kwargs):
            raise RuntimeError('The requests package is required for SonarQube automation')

        @staticmethod
        def post(*args, **kwargs):
            raise RuntimeError('The requests package is required for SonarQube automation')

    requests = _RequestsStub()

ROOT = Path(__file__).resolve().parent.parent

SONAR_HOST_URL = os.getenv('SONAR_HOST_URL')
SONAR_TOKEN = os.getenv('SONAR_TOKEN')
SONAR_PROJECT_KEY = os.getenv('SONAR_PROJECT_KEY')
LLM_API_KEY = os.getenv('LLM_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')
GITHUB_API_URL = os.getenv('GITHUB_API_URL', 'https://api.github.com')
GITHUB_CLONE_URL = os.getenv('GITHUB_CLONE_URL', '')
GIT_REMOTE = os.getenv('GIT_REMOTE', 'origin')
REPO_DIR = os.getenv('REPO_DIR', str(Path.cwd()))
BUILD_COMMAND = os.getenv('BUILD_COMMAND', './gradlew build')
TEST_COMMAND = os.getenv('TEST_COMMAND', './gradlew test')
SONAR_SCANNER_CMD = os.getenv('SONAR_SCANNER_CMD', 'sonar-scanner')
AI_FIX_BRANCH_PREFIX = os.getenv('AI_FIX_BRANCH_PREFIX', 'auto-ai-fix')
EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '')
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USE_SSL = os.getenv('SMTP_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
TARGET_BRANCH = os.getenv('TARGET_BRANCH', 'main')
MAX_ISSUES = int(os.getenv('MAX_ISSUES', '5'))

# basic logger
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=log_level, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)
log_file = os.getenv('AI_FIX_LOG_FILE', '.ai_fix.log')
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
logger.addHandler(file_handler)


def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        if k not in os.environ:
            os.environ[k] = v


def is_git_repo(path: Path) -> bool:
    return (path / '.git').exists()


def get_clone_url() -> str:
    if GITHUB_CLONE_URL:
        return GITHUB_CLONE_URL
    if not GITHUB_REPOSITORY:
        raise RuntimeError('GITHUB_REPOSITORY or GITHUB_CLONE_URL is required to clone the repository')
    return f'https://github.com/{GITHUB_REPOSITORY}.git'


def prepare_repository():
    repo_path = Path(REPO_DIR)
    if not repo_path.exists():
        clone_url = get_clone_url()
        print(f'Cloning repository from {clone_url} into {repo_path}')
        run(['git', 'clone', '--depth', '1', clone_url, str(repo_path)])
    if not is_git_repo(repo_path):
        raise RuntimeError(f'Repository directory is not a git repository: {repo_path}')
    os.chdir(repo_path)
    print(f'Using repository at {repo_path}')


def retry(max_attempts=3, backoff=1.0):
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = backoff
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        raise
                    logger.warning('Attempt %s failed: %s. Retrying in %.1fs', attempt, exc, delay)
                    time.sleep(delay + random.random() * 0.5)
                    delay *= 2
        return wrapper
    return deco


@retry(max_attempts=3, backoff=1.0)
def requests_get(*args, **kwargs):
    resp = requests.get(*args, **kwargs)
    if resp is None:
        raise RuntimeError('requests.get returned None')
    return resp


@retry(max_attempts=3, backoff=1.0)
def requests_post(*args, **kwargs):
    resp = requests.post(*args, **kwargs)
    if resp is None:
        raise RuntimeError('requests.post returned None')
    return resp


def is_valid_fix(file_path: str, fixed_text: str) -> bool:
    # Basic verification: for Python files, try parsing AST
    if file_path.endswith('.py'):
        try:
            ast.parse(fixed_text)
            return True
        except Exception as exc:
            logger.warning('Syntax check failed for %s: %s', file_path, exc)
            return False
    # For other languages, perform a non-empty check
    return bool(fixed_text and fixed_text.strip())


def write_audit(report: dict, path: str = '.ai_fix_report.json'):
    try:
        Path(path).write_text(json.dumps(report, indent=2), encoding='utf-8')
    except Exception:
        logger.exception('Failed to write audit report')


def refresh_config():
    global SONAR_HOST_URL, SONAR_TOKEN, SONAR_PROJECT_KEY, LLM_API_KEY
    global GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_API_URL, GITHUB_CLONE_URL, GIT_REMOTE, REPO_DIR, BUILD_COMMAND, TEST_COMMAND
    global SONAR_SCANNER_CMD, AI_FIX_BRANCH_PREFIX, EMAIL_RECIPIENTS
    global SMTP_SERVER, SMTP_PORT, SMTP_USE_SSL, SMTP_USERNAME, SMTP_PASSWORD
    global TARGET_BRANCH, MAX_ISSUES

    SONAR_HOST_URL = os.getenv('SONAR_HOST_URL')
    SONAR_TOKEN = os.getenv('SONAR_TOKEN')
    SONAR_PROJECT_KEY = os.getenv('SONAR_PROJECT_KEY')
    LLM_API_KEY = os.getenv('LLM_API_KEY')
    GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
    GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')
    GITHUB_API_URL = os.getenv('GITHUB_API_URL', 'https://api.github.com')
    GITHUB_CLONE_URL = os.getenv('GITHUB_CLONE_URL', '')
    GIT_REMOTE = os.getenv('GIT_REMOTE', 'origin')
    REPO_DIR = os.getenv('REPO_DIR', str(Path.cwd()))
    BUILD_COMMAND = os.getenv('BUILD_COMMAND', './gradlew build')
    TEST_COMMAND = os.getenv('TEST_COMMAND', './gradlew test')
    SONAR_SCANNER_CMD = os.getenv('SONAR_SCANNER_CMD', 'sonar-scanner')
    AI_FIX_BRANCH_PREFIX = os.getenv('AI_FIX_BRANCH_PREFIX', 'auto-ai-fix')
    EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '')
    SMTP_SERVER = os.getenv('SMTP_SERVER')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USE_SSL = os.getenv('SMTP_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
    SMTP_USERNAME = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    TARGET_BRANCH = os.getenv('TARGET_BRANCH', 'main')
    MAX_ISSUES = int(os.getenv('MAX_ISSUES', '5'))


def run(cmd, check=True, capture_output=False, env=None):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=capture_output, text=True, env=env)
    if result.returncode != 0 and check:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def get_sonar_issues():
    if not SONAR_HOST_URL or not SONAR_TOKEN or not SONAR_PROJECT_KEY:
        raise RuntimeError('SONAR_HOST_URL, SONAR_TOKEN, and SONAR_PROJECT_KEY are required')

    target = f"{SONAR_HOST_URL.rstrip('/')}/api/issues/search"
    query = {
        'projectKeys': SONAR_PROJECT_KEY,
        'resolved': 'false',
        'ps': '100',
        'additionalFields': 'comments'
    }
    response = requests_get(target, params=query, auth=(SONAR_TOKEN, ''))
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError('Invalid JSON from SonarQube issues API') from exc
    return data.get('issues', [])


def fetch_source_snippet(file_path, line, context=4):
    try:
        lines = Path(file_path).read_text(encoding='utf-8').splitlines()
    except Exception:
        return ''
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    snippet = '\n'.join(f'{idx + 1}: {lines[idx]}' for idx in range(start, end))
    return snippet


def build_prompt(file_path, issue):
    snippet = fetch_source_snippet(file_path, issue.get('line', 1))
    return (
        'You are an AI assistant for secure code quality remediation. '\
        'A SonarQube issue has been detected. Generate a minimal code fix for the affected file. '\
        'Return only the corrected file contents or a unified diff. Do not include explanations.\n\n'
        f'SonarQube issue: {issue.get("message")}\n'
        f'Severity: {issue.get("severity")}\n'
        f'Rule: {issue.get("rule")}\n'
        f'File: {file_path}\n'
        f'Line: {issue.get("line") or "unknown"}\n\n'
        'Context:\n'
        '"""\n'
        f'{snippet}\n'
        '"""\n\n'
        'If you cannot safely fix the issue, return the original file contents unchanged.'
    )


def call_llm(prompt):
    if not LLM_API_KEY:
        raise RuntimeError('LLM_API_KEY is required to generate fixes')

    endpoint = os.getenv('LLM_API_URL', 'https://api.openai.com/v1/chat/completions')
    headers = {
        'Authorization': f'Bearer {LLM_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': os.getenv('LLM_MODEL', 'gpt-4.1-mini'),
        'messages': [
            {'role': 'system', 'content': 'You are an AI developer assistant.'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': float(os.getenv('LLM_TEMPERATURE', '0.2')),
        'max_tokens': int(os.getenv('LLM_MAX_TOKENS', '1000')),
    }
    response = requests_post(endpoint, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    result = response.json()
    choices = result.get('choices', [])
    if not choices:
        raise RuntimeError('LLM returned no choices')
    return choices[0]['message']['content']


def strip_code_fences(text):
    fenced = re.sub(r'^```[a-zA-Z0-9]*\n', '', text)
    fenced = re.sub(r'\n```$', '', fenced)
    return fenced


def apply_fix(file_path, fixed_text):
    if fixed_text.strip().startswith('```'):
        fixed_text = strip_code_fences(fixed_text)

    if 'diff --git' in fixed_text or fixed_text.strip().startswith('---'):
        logger.info('Unified diff detected, saving patch to .ai_fix.patch for review')
        Path('.ai_fix.patch').write_text(fixed_text, encoding='utf-8')
        return False

    file_path_obj = Path(file_path)
    file_path_obj.write_text(fixed_text, encoding='utf-8')
    logger.info('Applied fix to %s', file_path)
    return True


def apply_fix_dryrun(file_path, fixed_text):
    # write an artifact describing the proposed change without modifying source
    name = Path(file_path).name
    artifact = f'.ai_fix_dryrun_{name}.patch'
    try:
        Path(artifact).write_text(fixed_text, encoding='utf-8')
        logger.info('Wrote dry-run artifact: %s', artifact)
        return True
    except Exception:
        logger.exception('Failed to write dry-run artifact %s', artifact)
        return False


def generate_fix_for_issue(issue, dry_run=False):
    file_path = issue.get('component', '').replace(f'{SONAR_PROJECT_KEY}:', '', 1)
    if not file_path or not Path(file_path).exists():
        print(f'Skipping issue because source file not found: {file_path}')
        return False

    try:
        prompt = build_prompt(file_path, issue)
        fixed_content = call_llm(prompt)
    except Exception as exc:
        logger.warning('Skipping issue because LLM fix generation failed: %s', exc)
        return False

    if not is_valid_fix(file_path, fixed_content):
        logger.warning('LLM produced an invalid fix for %s; saving for review', file_path)
        Path(f'.ai_fix_failed_{Path(file_path).name}.patch').write_text(fixed_content, encoding='utf-8')
        return False

    if dry_run:
        return apply_fix_dryrun(file_path, fixed_content)

    return apply_fix(file_path, fixed_content)


def run_validation_commands(build_command=BUILD_COMMAND, test_command=TEST_COMMAND):
    results = {}
    if build_command:
        print(f'Running build validation: {build_command}')
        results['build'] = run(shlex.split(build_command), check=False, capture_output=True)
    if test_command:
        print(f'Running test validation: {test_command}')
        results['test'] = run(shlex.split(test_command), check=False, capture_output=True)
    return results


def has_uncommitted_changes():
    result = run(['git', 'status', '--porcelain'], check=False, capture_output=True)
    return bool(result.stdout.strip())


def get_current_branch():
    result = run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], check=False, capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def branch_has_commits_ahead(branch, target_branch):
    result = run(['git', 'rev-list', '--count', f'{target_branch}..{branch}'], check=False, capture_output=True)
    if result.returncode != 0:
        return False
    try:
        return int(result.stdout.strip() or '0') > 0
    except ValueError:
        return False


def create_branch():
    branch_name = f'{AI_FIX_BRANCH_PREFIX}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}'
    run(['git', 'checkout', '-B', branch_name], check=False)
    return branch_name


def commit_changes(branch_name):
    if not has_uncommitted_changes():
        print('No changes detected after applying fixes. Skipping commit and PR creation.')
        return False

    run(['git', 'add', '.'])
    commit_result = run(['git', 'commit', '-m', 'Auto-fix SonarQube issues with AI agent'], check=False, capture_output=True)
    if commit_result.returncode != 0:
        print('Git commit failed or there was nothing to commit.')
        return False

    push_result = run(['git', 'push', '--set-upstream', GIT_REMOTE, branch_name], check=False, capture_output=True)
    if push_result.returncode != 0:
        print('Git push failed. Review the branch locally if needed.')
        return False
    return True


def get_existing_pull_request(branch_name):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return None
    api_url = f"{GITHUB_API_URL.rstrip('/')}/repos/{GITHUB_REPOSITORY}/pulls"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    params = {
        'state': 'open',
        'head': f'{GITHUB_REPOSITORY.split("/")[0]}:{branch_name}',
        'base': TARGET_BRANCH,
    }
    response = requests_get(api_url, params=params, headers=headers)
    response.raise_for_status()
    prs = response.json()
    if prs:
        return prs[0].get('html_url')
    return None


def create_pull_request(branch_name):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print('Skipping PR creation: missing GITHUB_TOKEN or GITHUB_REPOSITORY')
        return None

    existing_pr = get_existing_pull_request(branch_name)
    if existing_pr:
        print(f'Pull request already exists for {branch_name}: {existing_pr}')
        return existing_pr

    api_url = f"{GITHUB_API_URL.rstrip('/')}/repos/{GITHUB_REPOSITORY}/pulls"
    payload = {
        'title': f'AI auto-fix: SonarQube issues ({branch_name})',
        'head': branch_name,
        'base': TARGET_BRANCH,
        'body': 'This PR was generated automatically by the NOVA AI agent to address SonarQube issues.',
    }
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    response = requests_post(api_url, json=payload, headers=headers)
    response.raise_for_status()
    pr_data = response.json()
    logger.info('Created PR: %s', pr_data.get('html_url'))
    return pr_data.get('html_url')


def send_approval_email(pr_url):
    if not EMAIL_RECIPIENTS or not SMTP_SERVER or not SMTP_USERNAME or not SMTP_PASSWORD:
        print('Skipping approval email: email configuration is incomplete')
        return

    message = EmailMessage()
    message['Subject'] = 'AI agent created PR for SonarQube fixes'
    message['From'] = SMTP_USERNAME
    message['To'] = EMAIL_RECIPIENTS.split(',')
    message.set_content(
        f'The AI remediation agent created a Pull Request for SonarQube fixes:\n\n{pr_url}\n\n'
        'Review the changes and merge when ready.'
    )

    use_ssl = SMTP_USE_SSL or SMTP_PORT == 465
    smtp_client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_client(SMTP_SERVER, SMTP_PORT) as smtp:
        if not use_ssl:
            smtp.starttls()
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def run_sonar_scan():
    if not SONAR_HOST_URL:
        raise RuntimeError('SONAR_HOST_URL is required to run SonarQube scan')
    if not SONAR_TOKEN:
        raise RuntimeError('SONAR_TOKEN is required to run SonarQube scan')
    if not SONAR_PROJECT_KEY:
        raise RuntimeError('SONAR_PROJECT_KEY is required to run SonarQube scan')
    run(shlex.split(SONAR_SCANNER_CMD) + [f'-Dsonar.projectKey={SONAR_PROJECT_KEY}', f'-Dsonar.host.url={SONAR_HOST_URL}', f'-Dsonar.login={SONAR_TOKEN}'])


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Do not modify files or push; write audit artifacts instead')
    parser.add_argument('--max-issues', type=int, default=MAX_ISSUES)
    return parser.parse_args(argv)


def check_quality_gate():
    if not SONAR_HOST_URL or not SONAR_TOKEN or not SONAR_PROJECT_KEY:
        raise RuntimeError('SonarQube connection settings are required')

    status_url = f"{SONAR_HOST_URL.rstrip('/')}/api/qualitygates/project_status?projectKey={SONAR_PROJECT_KEY}"
    response = requests_get(status_url, auth=(SONAR_TOKEN, ''))
    response.raise_for_status()
    payload = response.json()
    project_status = payload.get('projectStatus', {})
    status = project_status.get('status', 'UNKNOWN')
    print(f'SonarQube quality gate status: {status}')
    return status


def main():
    # load .env if present to ease local configuration during runs
    load_dotenv(ROOT / '.env')
    refresh_config()
    args = parse_args()
    prepare_repository()

    try:
        issues = get_sonar_issues()
    except Exception as exc:
        print(f'Unable to fetch SonarQube issues: {exc}')
        return

    print(f'Found {len(issues)} open SonarQube issue(s)')

    if not issues:
        current_branch = get_current_branch()
        if current_branch and current_branch != TARGET_BRANCH and branch_has_commits_ahead(current_branch, TARGET_BRANCH):
            print(f'No SonarQube issues found, but branch {current_branch} is ahead of {TARGET_BRANCH}. Creating PR for current branch.')
            audit = {'fixed': [], 'failed': [], 'issues': []}
            branch_name = current_branch
            pr_url = create_pull_request(branch_name)
            if pr_url:
                send_approval_email(pr_url)
            audit['pr_url'] = pr_url
            audit['branch_name'] = branch_name
            audit['quality_gate'] = 'N/A'
            write_audit(audit)
            return
        print('No unresolved SonarQube issues found. Exiting.')
        return

    issues = issues[:int(os.getenv('MAX_ISSUES', str(args.max_issues)))]
    fixed_count = 0
    audit = {'fixed': [], 'failed': [], 'issues': []}
    for issue in issues:
        audit['issues'].append(issue)
        if generate_fix_for_issue(issue, dry_run=args.dry_run):
            fixed_count += 1
            audit['fixed'].append(issue)
        else:
            audit['failed'].append(issue)

    audit['dry_run'] = args.dry_run
    audit['timestamp'] = datetime.now(timezone.utc).isoformat()
    audit['issues_checked'] = len(issues)

    if args.dry_run:
        logger.info('Dry-run complete; no branch, commit, or PR was created')
        write_audit(audit)
        return

    if fixed_count == 0:
        print('No fixes were applied. Exiting without branch or PR creation.')
        return

    validation_results = run_validation_commands()
    validation_passed = True
    for key in ('build', 'test'):
        result = validation_results.get(key)
        if result is None:
            continue
        if result.returncode != 0:
            validation_passed = False
            print(f'{key} validation failed with exit code {result.returncode}')

    if validation_passed:
        logger.info('Build and test validation passed.')
    else:
        logger.warning('Build and test validation failed; continuing with branch creation for manual review.')

    run_sonar_scan()
    status = check_quality_gate()
    if status != 'OK':
        print('Quality gate still failing after automated fixes. Continuing with branch creation for review.')

    branch_name = create_branch()
    committed = commit_changes(branch_name)
    if not committed:
        print('Skipping PR creation because no committed changes were available.')
        return

    pr_url = create_pull_request(branch_name)
    if pr_url:
        send_approval_email(pr_url)

    audit['pr_url'] = pr_url
    audit['branch_name'] = branch_name
    audit['quality_gate'] = status
    try:
        write_audit(audit)
    except Exception:
        logger.exception('Failed to write audit report')


if __name__ == '__main__':
    main()
