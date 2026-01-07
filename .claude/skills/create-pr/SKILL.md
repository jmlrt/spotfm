---
name: create-pr
description: Create a pull request from current changes with interactive file selection, pre-commit validation, testing, and automated PR creation. Use when the user asks to "create a PR", "make a pull request", "open a PR", or wants to submit changes for review.
allowed-tools: Read, Grep, Glob, Bash(*), AskUserQuestion, TodoWrite
---

# Create Pull Request

This skill automates the entire pull request creation workflow with safety checks and best practices.

## Workflow Overview

1. **Branch Setup**: Fetch latest base branch, create/rebase feature branch
2. **File Selection**: Review and interactively select files to stage
3. **Security Check**: Verify no credentials, secrets, or PII in staged files
4. **Validation**: Run pre-commit hooks and fix issues
5. **Testing**: Run test suite to ensure changes don't break functionality
6. **Commit**: Create concise commit message and commit changes
7. **PR Creation**: Generate PR description and create draft PR

## Instructions

### Step 1: Determine Base Branch

Ask the user which base branch to use:
- Default: `main`
- Allow custom base branch selection

### Step 2: Fetch and Update Base Branch

```bash
# Fetch the latest changes from remote
git fetch origin

# Get current branch name
CURRENT_BRANCH=$(git branch --show-current)

# If not already on a feature branch, create one
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
  # Ask user for feature branch name
  # Suggest name based on changes or current branch from git status
fi
```

### Step 3: Rebase Feature Branch on Base Branch

```bash
# Non-interactive rebase
GIT_EDITOR=true git rebase --no-edit origin/<base-branch>

# If rebase fails, inform user and exit
if [ $? -ne 0 ]; then
  echo "Rebase failed. Please resolve conflicts manually."
  git rebase --abort
  exit 1
fi
```

### Step 4: Review and Select Files to Stage

**CRITICAL: Never use `git add --all` or `git add .`**

1. Get list of modified files:
```bash
git status --porcelain
```

2. Categorize files:
   - **Modified files** (M): Already tracked files with changes
   - **Untracked files** (?): New files not in git
   - **Deleted files** (D): Removed files

3. For each file category:
   - **Modified files**: Present to user, ask which to stage
   - **Untracked files**: Only suggest if they relate to other changes
   - **Deleted files**: Confirm deletion is intentional

4. Exclude files that should never be committed:
   - Respect `.gitignore` patterns
   - Skip temp files: `*.pyc`, `__pycache__/`, `.DS_Store`, `*.swp`, `*.tmp`
   - Skip cache directories: `.cache/`, `.pytest_cache/`, `htmlcov/`
   - Skip virtual environments: `.venv/`, `venv/`, `env/`
   - Skip build artifacts: `dist/`, `build/`, `*.egg-info/`

### Step 5: Security Check for Leaked Credentials

**CRITICAL: Check staged files for sensitive data**

Scan for common patterns:
```bash
# Check for potential secrets in staged files
git diff --cached | grep -iE "(password|secret|api[_-]?key|token|credential|private[_-]?key|aws|stripe)" --color=always
```

Look for:
- API keys (e.g., `api_key = "sk_live_..."`)
- Passwords (e.g., `password = "..."`)
- Private keys (e.g., `-----BEGIN PRIVATE KEY-----`)
- AWS credentials (e.g., `AWS_SECRET_ACCESS_KEY`)
- Database URLs with credentials
- OAuth tokens
- Email addresses in comments (potential PII)

If found:
1. **STOP immediately**
2. Unstage the problematic files
3. Inform user which files contain potential secrets
4. Ask user to remove secrets or use environment variables
5. Do NOT proceed until resolved

### Step 6: Run Pre-commit Hooks

```bash
# Run pre-commit on staged files
make pre-commit

# If pre-commit makes changes, show them and ask to stage
if [ $? -ne 0 ]; then
  echo "Pre-commit hooks made changes. Review and stage them."
  git diff
fi

# Re-run to ensure all hooks pass
make pre-commit
```

If hooks fail after fixes:
1. Show the errors to user
2. Ask if they want to fix manually or skip hooks (not recommended)
3. Do NOT proceed until hooks pass

### Step 7: Run Tests

```bash
# Run full test suite
make test

# If tests fail, show output and stop
if [ $? -ne 0 ]; then
  echo "Tests failed. Please fix before creating PR."
  exit 1
fi
```

**Coverage requirement**: Ensure modified modules have ≥90% coverage
```bash
# For modified Python files, check coverage
uv run pytest tests/test_<module>.py --cov=spotfm.<module> --cov-report=term-missing
```

### Step 8: Create Commit Message

Generate a concise commit message following project guidelines:

**Structure**:
```
Brief summary (50 chars or less)

- Key change 1
- Key change 2
- Key change 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Guidelines**:
- Be concise: Focus on most important changes
- Use bullet points for clarity
- Highlight impact (test coverage, performance, breaking changes)
- Skip implementation details
- Keep it scannable

Save to temporary file:
```bash
cat > COMMIT_MESSAGE.md <<'EOF'
[Generated commit message]
EOF
```

### Step 9: Commit Changes

```bash
# Commit with message from file
git commit -F COMMIT_MESSAGE.md

# Verify commit was created
git log -1 --oneline
```

### Step 10: Check for GitHub PR Template

```bash
# Look for PR template in common locations
if [ -f .github/PULL_REQUEST_TEMPLATE.md ]; then
  echo "Found PR template at .github/PULL_REQUEST_TEMPLATE.md"
  TEMPLATE_PATH=".github/PULL_REQUEST_TEMPLATE.md"
elif [ -f .github/pull_request_template.md ]; then
  echo "Found PR template at .github/pull_request_template.md"
  TEMPLATE_PATH=".github/pull_request_template.md"
elif [ -f PULL_REQUEST_TEMPLATE.md ]; then
  echo "Found PR template at PULL_REQUEST_TEMPLATE.md"
  TEMPLATE_PATH="PULL_REQUEST_TEMPLATE.md"
else
  echo "No PR template found"
  TEMPLATE_PATH=""
fi
```

If template exists, read it and incorporate its structure into the PR description.

### Step 11: Create PR Description

Generate a concise PR description:

**Default Structure** (if no template):
```markdown
## Summary
- Brief overview of changes (2-3 bullets)

## Changes
- Key change 1
- Key change 2
- Key change 3

## Testing
- Test coverage: X%
- Tests added/modified: Y
- All tests passing: ✅

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated (if needed)
- [ ] Pre-commit hooks pass
- [ ] No secrets or PII leaked

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

If template exists, follow its structure but keep content concise.

Save to temporary file:
```bash
cat > PR_DESCRIPTION.md <<'EOF'
[Generated PR description]
EOF
```

### Step 12: Push Branch and Create Draft PR

```bash
# Push feature branch to remote
git push -u origin <feature-branch>

# Create draft PR using gh CLI
gh pr create \
  --base <base-branch> \
  --head <feature-branch> \
  --draft \
  --body-file PR_DESCRIPTION.md

# If gh pr create fails, show error and suggest manual creation
if [ $? -ne 0 ]; then
  echo "Failed to create PR via gh CLI. You may need to:"
  echo "1. Install GitHub CLI: brew install gh"
  echo "2. Authenticate: gh auth login"
  echo "3. Or create PR manually at: https://github.com/<repo>/compare"
fi
```

### Step 13: Cleanup Temporary Files

```bash
# Remove temporary message files
rm -f COMMIT_MESSAGE.md PR_DESCRIPTION.md

# Confirm cleanup
echo "Temporary files removed"
```

### Step 14: Success Summary

Display summary:
```
✅ Pull Request Created Successfully!

Branch: <feature-branch>
Base: <base-branch>
PR URL: [URL from gh pr create output]

Files changed: X
Commits: 1
Tests: All passing
Coverage: Y%

Next steps:
- Review the PR description and edit if needed
- Request reviewers
- Mark as ready for review when appropriate
```

## Error Handling

Handle common errors gracefully:

1. **Rebase conflicts**: Abort rebase, inform user, exit
2. **Pre-commit failures**: Show errors, allow manual fix, re-run
3. **Test failures**: Show output, stop process, exit
4. **Secrets detected**: Stop immediately, unstage files, warn user
5. **Push failures**: Show error, suggest checking permissions
6. **gh CLI not installed**: Provide installation instructions

## Safety Checks

**NEVER proceed if**:
- Secrets or credentials detected in staged files
- Tests are failing
- Pre-commit hooks fail (without user override)
- Rebase has conflicts
- Working directory has merge conflicts

## Notes

- This skill operates in **non-interactive mode** for git operations (using `GIT_EDITOR=true --no-edit`)
- User interaction happens through `AskUserQuestion` tool for file selection and branch naming
- All git operations are safe and reversible (no force push, no destructive commands)
- Temporary files (COMMIT_MESSAGE.md, PR_DESCRIPTION.md) are always cleaned up
- Draft PRs allow for further edits before marking ready for review

## Examples

### Example 1: Basic PR Creation

```
User: "Create a PR for my changes"

1. Ask: "Base branch? (default: main)"
2. Fetch: origin/main
3. Current branch: feature/add-dupes
4. Rebase: feature/add-dupes onto origin/main
5. Show modified files:
   - M spotfm/spotify/dupes.py
   - M tests/test_dupes.py
   - ?? TODO.md (related to changes)
6. Ask: "Stage these files?"
7. Security check: ✅ No secrets detected
8. Run pre-commit: ✅ Passed
9. Run tests: ✅ 179 passed, coverage 87%
10. Generate commit message
11. Commit changes
12. Generate PR description
13. Push and create draft PR
14. Cleanup temp files
15. Show success summary with PR URL
```

### Example 2: Handling Secrets

```
User: "Create a PR"

1-6. [Same as Example 1]
7. Security check: ⚠️ Found "api_key" in config.py
8. STOP: Unstage config.py
9. Warn: "Potential secret detected in config.py line 42"
10. Exit: "Please remove secrets and try again"
```

### Example 3: Custom Base Branch

```
User: "Create a PR against develop branch"

1. Use base: develop (specified by user)
2. Fetch: origin/develop
3. [Continue normal workflow]
```
