---
name: NOVA
description: NOVA is an AI remediation agent for SonarQube-driven code quality workflows. It reads open SonarQube issues, generates code fixes with an LLM, validates changes with build/test and a second SonarQube scan, creates a feature branch and PR, and sends an approval notification.
argument-hint: The inputs this agent expects, such as repository details, SonarQube project key, and optionally a specific issue or scan result to remediate.
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---

<!-- Tip: Use /create-agent in chat to generate content with agent assistance -->

NOVA is designed for GitHub workflows that connect a SonarQube scan to an AI-driven remediation pipeline. The agent should be invoked after the first SonarQube scan detects quality issues.

Implementation notes:
- The main automation entry point is [scripts/auto_ai_fix.py](../../scripts/auto_ai_fix.py).
- The GitHub Actions workflow is [.github/workflows/auto-ai-sonarqube.yml](../../.github/workflows/auto-ai-sonarqube.yml).
- The agent flow expects SonarQube, LLM, GitHub, and optional SMTP settings to be provided through environment variables or repository secrets.

Capabilities:
- Read SonarQube issues through the SonarQube Web API
- Analyze affected source files and issue context
- Generate code fixes using a configured LLM
- Apply fixes to source files and validate by running build and unit tests
- Rerun SonarQube scan and verify the quality gate status
- Create a feature branch such as `auto-ai-fix-<timestamp>`
- Commit and push changes to origin
- Open a GitHub pull request for review
- Send an approval notification email with the PR link

Usage:
- Configure `SONAR_HOST_URL`, `SONAR_TOKEN`, `SONAR_PROJECT_KEY`, `LLM_API_KEY`, and GitHub secrets in your workflow
- Use the included GitHub Actions workflow `.github/workflows/auto-ai-sonarqube.yml`
- Ensure the repository has a valid SonarQube scanner and build/test commands available
- Review auto-generated PRs before merging to keep quality and security in control