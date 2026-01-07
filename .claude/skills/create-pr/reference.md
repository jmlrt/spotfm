# Create PR Skill - Reference Guide

## Quick Usage

Simply ask Claude Code to create a PR:
- "Create a PR"
- "Make a pull request"
- "Open a PR for my changes"
- "Create a PR against develop branch"

The skill will automatically:
1. ✅ Fetch latest base branch
2. ✅ Create/rebase feature branch
3. ✅ Let you select which files to stage
4. ✅ Check for leaked secrets/credentials
5. ✅ Run pre-commit hooks
6. ✅ Run tests
7. ✅ Generate commit message
8. ✅ Generate PR description
9. ✅ Create draft PR on GitHub
10. ✅ Clean up temporary files

## Prerequisites

### GitHub CLI
The skill uses `gh` CLI to create PRs. Install it:

```bash
# macOS
brew install gh

# Authenticate
gh auth login
```

### Git Configuration
Ensure your git is configured:

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## Behavior Details

### File Selection
**IMPORTANT**: The skill will NEVER use `git add --all` or `git add .`

Instead, it will:
1. Show you all modified files
2. Show untracked files (only if related to changes)
3. Ask you to select which files to stage
4. Automatically exclude:
   - `.gitignore` patterns
   - Temp files (*.pyc, *.swp, .DS_Store)
   - Cache directories (.cache/, .pytest_cache/)
   - Virtual environments (.venv/)
   - Build artifacts (dist/, build/)

### Security Checks
The skill scans for common secret patterns:
- API keys (api_key, API_KEY)
- Passwords (password, PASSWORD)
- Tokens (token, TOKEN, Bearer)
- Private keys (-----BEGIN PRIVATE KEY-----)
- AWS credentials (AWS_SECRET_ACCESS_KEY)
- Database URLs with credentials
- OAuth tokens

If detected, the process **STOPS immediately** and you'll need to remove secrets before proceeding.

### Pre-commit Hooks
The skill runs `make pre-commit` which includes:
- Code formatting (ruff)
- Linting (ruff)
- Import sorting
- Type checking
- Other configured hooks

If hooks make changes:
1. Changes are shown to you
2. You're asked to review and stage them
3. Hooks are re-run to ensure they pass

### Testing
The skill runs `make test` which:
- Runs all 179+ tests
- Checks coverage (requires ≥90% for modified modules)
- Fails the PR process if any tests fail

You can skip tests by manually creating commits, but this is **not recommended**.

### Commit Messages
Generated commit messages follow the project style guide:

```
Brief summary (50 chars or less)

- Key change 1
- Key change 2
- Key change 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

Messages are:
- Concise (focus on key changes)
- Scannable (bullet points)
- Informative (include impact/metrics)

### PR Descriptions
Generated PR descriptions follow this structure (unless a template exists):

```markdown
## Summary
- Brief overview of changes

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

### Draft PRs
PRs are created as **drafts** by default, allowing you to:
- Review the description and edit if needed
- Add additional commits
- Request reviewers
- Mark as "ready for review" when appropriate

## Customization

### Custom Base Branch
By default, PRs target `main` branch. To use a different base:

```
"Create a PR against develop branch"
"Make a PR targeting release/v2.0"
```

### Feature Branch Naming
If you're on `main` or `master`, the skill will ask you to name a feature branch.

Suggested naming conventions:
- `feature/description` - New features
- `fix/description` - Bug fixes
- `refactor/description` - Refactoring
- `docs/description` - Documentation
- `test/description` - Test improvements

## Troubleshooting

### "gh: command not found"
Install GitHub CLI: `brew install gh` (macOS) or see https://cli.github.com/

### "gh auth required"
Run: `gh auth login` and follow the prompts

### "Rebase failed"
You have conflicts between your branch and the base branch. Resolve them manually:
```bash
git rebase --abort  # Exit the rebase
# Manually resolve conflicts
git rebase origin/main
```

### "Pre-commit hooks failed"
Review the error output. Common issues:
- Formatting errors (auto-fixed)
- Linting errors (may need manual fix)
- Type errors (need manual fix)

### "Tests failed"
Review the test output and fix failing tests before creating the PR.

### "Secret detected"
Remove the secret from your code:
1. Use environment variables
2. Use config files (excluded in .gitignore)
3. Use secret management tools

## Non-Interactive Mode

All git operations run in **non-interactive mode**:
- `GIT_EDITOR=true` prevents editor from opening
- `--no-edit` flag on rebase prevents commit message editing
- User interaction happens only through Claude's `AskUserQuestion` tool

This ensures the process is:
- Fully automated
- Reproducible
- Safe (no unexpected interactive prompts)

## What Happens to Temporary Files

The skill creates two temporary files:
- `COMMIT_MESSAGE.md` - Commit message content
- `PR_DESCRIPTION.md` - PR description content

Both are:
1. Created in the project root
2. Used for git commit / gh pr create
3. **Automatically deleted** after use

If the process is interrupted, you may find these files in your repo. They're safe to delete manually.

## Safety Guarantees

The skill will NEVER:
- Force push (`git push --force`)
- Delete branches without confirmation
- Modify commits you didn't create
- Skip security checks
- Proceed with failing tests
- Commit secrets or credentials
- Use `git add --all` without review

The skill ALWAYS:
- Asks before staging files
- Checks for secrets before committing
- Runs pre-commit hooks
- Runs tests before pushing
- Creates draft PRs (not ready for review)
- Cleans up temporary files

## Examples

### Example 1: Simple Feature PR
```
You: "Create a PR"
Claude: "Which base branch? (default: main)"
You: "main"
Claude: [Fetches origin/main, rebases current branch]
Claude: "Found 3 modified files, stage all?"
You: "Yes"
Claude: [Security check ✅, pre-commit ✅, tests ✅]
Claude: [Creates commit, generates PR, pushes]
Claude: "✅ PR created: https://github.com/user/repo/pull/42"
```

### Example 2: Feature PR with New Files
```
You: "Create a PR"
Claude: "Which base branch?"
You: "main"
Claude: "Found 2 modified and 3 untracked files. Stage these?"
  - M spotfm/spotify/dupes.py
  - M tests/test_dupes.py
  - ?? TODO.md (related)
  - ?? notes.txt (unrelated - skip)
  - ?? .DS_Store (temp - skip)
You: "Stage modified and TODO.md"
Claude: [Continues with security checks, pre-commit, tests, PR creation]
```

### Example 3: Custom Base Branch
```
You: "Create a PR against develop"
Claude: [Fetches origin/develop, rebases]
Claude: "Current branch: feature/add-auth"
Claude: [Continues with normal workflow]
```

### Example 4: Secret Detected
```
You: "Create a PR"
Claude: [File selection, staging]
Claude: "⚠️ Security check FAILED"
        "Found potential secret in config.py:42"
        "Pattern: api_key = 'sk_live_...'"
Claude: "Please remove secrets and try again."
[Process stops, files unstaged]
```

## See Also

- [Project commit message guidelines](../../CLAUDE.md#commit-messages)
- [Testing guidelines](../../CLAUDE.md#testing)
- [GitHub CLI documentation](https://cli.github.com/manual/)
- [Pre-commit hooks](https://pre-commit.com/)
