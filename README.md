# CodeGuardian AI Auto-Fix Agent

This repository contains an automated SonarQube remediation agent that:

- reads SonarQube issues via the Web API
- generates candidate code fixes with an LLM
- validates changes locally against build and test commands
- reruns SonarQube quality gate checks
- creates a feature branch like `auto-ai-fix-YYYYMMDDHHMMSS`
- pushes the branch to GitHub
- opens a pull request against `main`
- sends an approval email with the PR link

## Requirements

- Python 3.12
- `requests` package
- Git repository with write access
- SonarQube server access and valid project key
- GitHub token with `contents: write` and `pull-requests: write`

## Setup

1. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Copy `env.example` to `.env` and fill in secrets:

```bash
cp env.example .env
```

3. Run the agent in dry-run mode first:

```bash
python scripts/auto_ai_fix.py --dry-run
```

4. If the dry-run artifacts look good, run without dry-run:

```bash
python scripts/auto_ai_fix.py
```

## Local scenario test

Use your `.env` to configure SonarQube, GitHub, LLM, and SMTP settings, then run the workflow locally:

```bash
python -m pip install -r requirements.txt
python scripts/auto_ai_fix.py --dry-run
python scripts/auto_ai_fix.py
```

This will:

- connect to the SonarQube project at `SONAR_HOST_URL`
- collect unresolved issues
- generate fixes and apply them locally
- create a feature branch prefixed with `auto-ai-fix-`
- open a pull request against `main`
- send an approval email when configured

## Environment variables

Use `.env` or CI secrets for the following:

- `SONAR_HOST_URL`
- `SONAR_TOKEN`
- `SONAR_PROJECT_KEY`
- `LLM_API_KEY`
- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`
- `BUILD_COMMAND` (default `./gradlew build`)
- `TEST_COMMAND` (default `./gradlew test`)
- `SONAR_SCANNER_CMD` (default `sonar-scanner`)
- `AI_FIX_BRANCH_PREFIX` (default `auto-ai-fix`)
- `GITHUB_API_URL` (default `https://api.github.com`)
- `GITHUB_CLONE_URL` (optional, overrides derived clone URL)
- `GIT_REMOTE` (default `origin`)
- `REPO_DIR` (default current working directory)
- `EMAIL_RECIPIENTS`
- `SMTP_SERVER`
- `SMTP_PORT` (default `587`)
- `SMTP_USE_SSL` (default `false`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `TARGET_BRANCH` (default `main`)
- `MAX_ISSUES` (default `5`)
- `LOG_LEVEL` (default `INFO`)
- `AI_FIX_LOG_FILE` (default `.ai_fix.log`)

## Testing

Run unit tests with:

```bash
pytest -q
```

## CI

- `python-ci.yml` runs tests on push and pull requests.
- `auto-ai-sonarqube.yml` runs the SonarQube scan and automation agent on `main`.
- `auto-ai-pr-dry-run.yml` runs the agent in dry-run mode on pull requests to validate behavior without pushing changes.
- `auto-ai-pr-dry-run.yml` also captures and uploads a diff artifact named `ai_fix_dry_run.diff` for review.
