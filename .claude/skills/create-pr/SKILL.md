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

### Step 3: Check Branch Status and Handle Rebase

**Check if branch is up-to-date first:**

```bash
# Check if feature branch is already up-to-date with base
git fetch origin
if git merge-base --is-ancestor origin/<base-branch> HEAD; then
  echo "✅ Branch is already up to date with <base-branch>"
  NEEDS_REBASE=false
else
  echo "Branch needs to be rebased on <base-branch>"
  NEEDS_REBASE=true
fi
```

**Handle unstaged changes before rebasing:**

```bash
# Only rebase if needed
if [ "$NEEDS_REBASE" = true ]; then
  # Check for unstaged changes
  if ! git diff-files --quiet; then
    echo "⚠️ You have unstaged changes. These will be preserved during rebase."
    # Ask user if they want to proceed
    # Options: 1) Stash and rebase, 2) Skip rebase, 3) Cancel
  fi

  # Non-interactive rebase (removed --no-edit flag for compatibility)
  GIT_EDITOR=true git rebase origin/<base-branch>

  # If rebase fails, inform user and exit
  if [ $? -ne 0 ]; then
    echo "❌ Rebase failed. Please resolve conflicts manually."
    git rebase --abort
    exit 1
  fi

  echo "✅ Successfully rebased on <base-branch>"
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

**Improved pattern matching to reduce false positives:**

```bash
# Look for actual assignment patterns, not just keywords in documentation
git diff --cached | grep -iE '(password|secret|api[_-]?key|token|credential|private[_-]?key|aws_secret|stripe)["\s]*[:=]["\s]*["\x27][^"\x27]{8,}' --color=always

# Also check for common secret formats
git diff --cached | grep -E '(sk_live_|pk_live_|sk_test_|-----BEGIN (PRIVATE|RSA) KEY-----|ghp_|gho_|AKIA[0-9A-Z]{16})' --color=always
```

**Smarter detection:**
- Ignore markdown code blocks (lines starting with ` ``` ` or indented with 4+ spaces in .md files)
- Ignore comments explaining security (e.g., "# Check for passwords")
- Focus on actual assignments: `password = "value"`, `api_key: "value"`
- Look for common secret prefixes: `sk_live_`, `ghp_`, `AKIA`, etc.

Look for:
- API keys with assignment (e.g., `api_key = "sk_live_..."`)
- Passwords with values (e.g., `password = "actualpassword"`)
- Private keys (e.g., `-----BEGIN PRIVATE KEY-----`)
- AWS credentials (e.g., `AWS_SECRET_ACCESS_KEY = "AKIA..."`)
- Database URLs with credentials (e.g., `postgres://user:pass@host`)
- OAuth tokens with assignment
- Email addresses in code (potential PII)

**If potential secrets found:**
1. Review the matches to filter out false positives (documentation, examples)
2. If real secrets detected:
   - **STOP immediately**
   - Show user the specific lines with secrets
   - Ask user to confirm if these are real secrets or false positives
3. If confirmed as secrets:
   - Unstage the problematic files
   - Inform user which files contain secrets
   - Suggest using environment variables or secret management
4. Do NOT proceed until resolved

### Step 6: Run Pre-commit Hooks

**CRITICAL: Run pre-commit ONLY on staged files to avoid false failures**

```bash
# Get list of staged files
STAGED_FILES=$(git diff --cached --name-only)

# Run pre-commit only on staged files (not all files)
if [ -n "$STAGED_FILES" ]; then
  uv run pre-commit run --files $STAGED_FILES
  PRECOMMIT_EXIT=$?
else
  echo "No staged files to check"
  PRECOMMIT_EXIT=0
fi

# If pre-commit makes changes, show them
if [ $PRECOMMIT_EXIT -ne 0 ]; then
  echo "⚠️ Pre-commit hooks made changes or found issues."
  echo "Modified files:"
  git diff --name-only

  # If hooks auto-fixed files, they need to be staged
  if git diff --name-only | grep -q .; then
    echo "Auto-fixes were applied. Staging fixed files..."
    git add $STAGED_FILES
  fi

  # Re-run to ensure all hooks pass
  uv run pre-commit run --files $STAGED_FILES
  if [ $? -ne 0 ]; then
    echo "❌ Pre-commit hooks still failing after auto-fixes"
    # Show errors to user
    # Ask if they want to fix manually or skip hooks (not recommended)
  fi
fi
```

**Why run only on staged files:**
- Prevents failures from unrelated code changes in working directory
- Faster execution (only checks files being committed)
- Avoids confusing errors about code not part of the PR

If hooks fail after fixes:
1. Show the specific errors to user
2. Ask if they want to:
   - Fix manually and re-run
   - Skip hooks (not recommended, ask for confirmation)
   - Cancel PR creation
3. Do NOT proceed until hooks pass (unless user explicitly overrides)

### Step 7: Run Tests

**Smart test execution with option to skip for docs-only changes:**

```bash
# Check if changes are documentation-only
STAGED_FILES=$(git diff --cached --name-only)
DOC_ONLY=$(echo "$STAGED_FILES" | grep -vE '\.(md|txt|rst|pdf|png|jpg|svg)$' || true)

if [ -z "$DOC_ONLY" ]; then
  echo "📝 Detected documentation-only changes"
  # Ask user: "Skip test execution for docs-only PR? (Y/n)"
  SKIP_TESTS=true
else
  SKIP_TESTS=false
fi

# Run tests unless skipped
if [ "$SKIP_TESTS" = false ]; then
  echo "🧪 Running test suite..."
  make test
  TEST_EXIT=$?

  # If tests fail, analyze if failures are in staged or unstaged code
  if [ $TEST_EXIT -ne 0 ]; then
    echo "❌ Tests failed"

    # Check if failures are related to staged files
    # Parse test output to see which modules failed
    echo "Analyzing test failures..."

    # If failures are in unstaged code, offer to continue anyway
    # Ask user: "Test failures detected in unstaged code (not part of this PR). Continue anyway? (y/N)"
  fi
else
  echo "⏭️  Skipping tests for documentation-only changes"
fi
```

**Handling test failures:**
1. **Failures in staged code**: STOP and require fixes
2. **Failures in unstaged code**: Warn user, but allow proceeding if they confirm
3. **All tests pass**: Continue to commit

**Coverage requirement**: Ensure modified modules have ≥90% coverage
```bash
# For modified Python files, optionally check coverage
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

# Check if gh CLI is available
if ! command -v gh &> /dev/null; then
  echo "❌ GitHub CLI (gh) is not installed"
  echo "Install with: brew install gh"
  echo "Or create PR manually at: https://github.com/<repo>/pull/new/<feature-branch>"
  exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
  echo "❌ Not authenticated with GitHub"
  echo "Run: gh auth login"
  exit 1
fi

# Create draft PR using gh CLI
gh pr create \
  --base <base-branch> \
  --head <feature-branch> \
  --draft \
  --title "<pr-title>" \
  --body-file PR_DESCRIPTION.md

# Capture PR URL
PR_URL=$(gh pr view --json url -q .url)

if [ $? -ne 0 ]; then
  echo "❌ Failed to create PR"
  echo "Possible issues:"
  echo "1. No permission to create PR in this repository"
  echo "2. Branch already has an open PR"
  echo "3. Network connectivity issues"
  echo ""
  echo "Try creating manually at: https://github.com/<repo>/pull/new/<feature-branch>"
  exit 1
fi

echo "✅ Draft PR created: $PR_URL"
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

1. **Unstaged changes during rebase**: Inform user, offer to stash or skip rebase
2. **Rebase conflicts**: Abort rebase, inform user, exit
3. **Pre-commit failures**: Show errors, allow manual fix, re-run (only on staged files)
4. **Test failures in staged code**: STOP and require fixes
5. **Test failures in unstaged code**: Warn user, allow proceeding with confirmation
6. **Secrets detected**: Review for false positives, stop if confirmed, unstage files
7. **Push failures**: Show error, suggest checking permissions
8. **gh CLI not installed**: Provide installation instructions and manual PR URL
9. **gh CLI not authenticated**: Provide auth instructions
10. **Branch already up-to-date**: Skip rebase, continue workflow

## Safety Checks

**NEVER proceed if**:
- Real secrets or credentials detected in staged files (after filtering false positives)
- Tests are failing in staged code
- Pre-commit hooks fail on staged files (without user override)
- Rebase has conflicts
- Working directory has merge conflicts

**MAY proceed with user confirmation if**:
- Tests fail in unstaged code (unrelated to PR)
- Documentation-only changes (can skip tests)
- User explicitly overrides pre-commit failures (not recommended)

## Notes

- This skill operates in **non-interactive mode** for git operations (using `GIT_EDITOR=true`)
- The `--no-edit` flag has been removed from rebase for compatibility with older git versions
- User interaction happens through `AskUserQuestion` tool for file selection and branch naming
- All git operations are safe and reversible (no force push, no destructive commands)
- Temporary files (COMMIT_MESSAGE.md, PR_DESCRIPTION.md) are always cleaned up
- Draft PRs allow for further edits before marking ready for review
- Pre-commit runs ONLY on staged files to prevent false failures from unstaged code
- Test failures in unstaged code won't block PR creation (with user confirmation)
- Security scan uses improved patterns to reduce false positives from documentation

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
