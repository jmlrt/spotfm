# Create PR Skill

A comprehensive Claude Code skill for creating pull requests with safety checks and best practices.

## Overview

This skill automates the entire PR creation workflow, from fetching the latest base branch to creating a draft PR on GitHub. It includes multiple validation checkpoints to ensure code quality, security, and test coverage.

## Files

- **[SKILL.md](SKILL.md)** - Main skill definition with step-by-step instructions for Claude
- **[reference.md](reference.md)** - Quick reference guide for users
- **[examples.md](examples.md)** - Detailed usage examples and troubleshooting scenarios
- **README.md** - This file

## Quick Start

Simply ask Claude Code:
```
Create a PR
```

Or with a custom base branch:
```
Create a PR against develop
```

## What It Does

1. ✅ Fetches latest base branch (default: main)
2. ✅ Creates feature branch if on main/master
3. ✅ Rebases feature branch on base branch (non-interactive)
4. ✅ Shows modified/untracked files for selection
5. ✅ Scans for leaked credentials/secrets
6. ✅ Runs pre-commit hooks
7. ✅ Runs test suite
8. ✅ Generates concise commit message
9. ✅ Generates PR description
10. ✅ Creates draft PR on GitHub
11. ✅ Cleans up temporary files

## Key Features

### Safety First
- **Never uses `git add --all`** - Files are selected interactively
- **Secret detection** - Scans for API keys, passwords, tokens, etc.
- **Pre-commit validation** - Ensures code quality standards
- **Test enforcement** - All tests must pass before PR creation
- **Draft PRs** - PRs created as drafts for review

### Smart File Selection
- Automatically excludes temp files (.DS_Store, *.pyc, etc.)
- Respects .gitignore patterns
- Only suggests untracked files if related to changes
- Filters out cache directories and build artifacts

### Non-Interactive Mode
- Uses `GIT_EDITOR=true --no-edit` for git operations
- No interactive prompts during git rebase
- User interaction through Claude's `AskUserQuestion` tool
- Fully automated workflow

### Comprehensive Validation
- Security checks for leaked credentials
- Pre-commit hooks (formatting, linting, type checking)
- Full test suite execution
- Coverage verification (≥90% for modified modules)

## Prerequisites

### Required
- **Git** - Version control
- **GitHub CLI (`gh`)** - For creating PRs
  ```bash
  brew install gh
  gh auth login
  ```

### Optional
- **make** - For running pre-commit and tests
- **uv** - Python package manager (for tests)

## Usage Examples

See [examples.md](examples.md) for detailed scenarios, including:
- Basic PR creation
- Custom base branches
- Handling secrets
- Pre-commit failures
- Test failures
- Rebase conflicts
- Using PR templates

## Configuration

The skill uses permissions defined in `.claude/settings.local.json`:
- `git add`, `commit`, `push`, `rebase`, `fetch`, `branch`, `status`, `diff`, `log`, `show`
- `gh pr create`
- `make pre-commit`, `make test`
- `cat`, `rm`, `grep`, `find`

## Workflow Details

### Branch Management
1. Fetches latest from remote
2. Checks current branch
3. Creates feature branch if on main/master
4. Rebases on base branch

### File Staging
1. Lists all modified files
2. Lists untracked files (filtered)
3. User selects which to stage
4. Never stages temp or cache files

### Security Scanning
Searches for patterns like:
- `api_key`, `API_KEY`
- `password`, `PASSWORD`
- `token`, `TOKEN`
- `secret`, `SECRET`
- Private keys
- AWS credentials
- Database URLs with credentials

### Validation Pipeline
1. **Security check** - Scan staged files for secrets
2. **Pre-commit** - Run hooks, stage fixes if needed
3. **Tests** - Run full test suite
4. **Coverage** - Verify ≥90% for modified modules

### Commit & PR
1. Generate commit message (project style)
2. Commit changes
3. Check for PR template
4. Generate PR description
5. Push branch
6. Create draft PR
7. Clean up temp files

## Error Handling

The skill handles:
- ❌ Rebase conflicts (abort and exit)
- ❌ Secrets detected (unstage and exit)
- ❌ Pre-commit failures (show errors, allow fixes)
- ❌ Test failures (show output and exit)
- ❌ gh CLI not installed (show instructions)
- ❌ gh not authenticated (show setup steps)

## Commit Message Format

```
Brief summary (50 chars or less)

- Key change 1
- Key change 2
- Key change 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

## PR Description Format

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

## Temporary Files

The skill creates and cleans up:
- `COMMIT_MESSAGE.md` - Commit message content
- `PR_DESCRIPTION.md` - PR description content

Both are automatically deleted after use.

## Troubleshooting

### gh command not found
```bash
brew install gh  # macOS
# or see https://cli.github.com/
```

### gh auth required
```bash
gh auth login
```

### Rebase conflicts
```bash
git rebase --abort
# Resolve conflicts manually
git rebase origin/main
```

### Tests failed
Review test output and fix issues before retrying.

### Secrets detected
Remove secrets from code and use environment variables instead.

## Best Practices

1. **Always review** the generated commit message and PR description
2. **Request reviewers** after creating the draft PR
3. **Mark as ready** only when the PR is complete
4. **Use feature branches** with descriptive names
5. **Keep PRs focused** on a single feature or fix

## Integration with Project

This skill integrates with:
- Project commit message guidelines (CLAUDE.md)
- Testing requirements (≥90% coverage)
- Pre-commit hooks configuration
- GitHub PR templates (if present)

## Customization

To customize the skill:
1. Edit [SKILL.md](SKILL.md) for workflow changes
2. Update [reference.md](reference.md) for documentation
3. Add examples to [examples.md](examples.md)
4. Restart Claude Code to load changes

## Security Guarantees

The skill will **NEVER**:
- Force push to remote
- Delete branches without confirmation
- Skip security checks
- Proceed with failing tests
- Commit secrets or credentials
- Use `git add --all` without review

The skill **ALWAYS**:
- Asks before staging files
- Checks for secrets before committing
- Runs pre-commit hooks
- Runs tests before pushing
- Creates draft PRs (not ready for review)
- Cleans up temporary files

## Support

For issues or questions:
1. Check [examples.md](examples.md) for troubleshooting scenarios
2. Review [reference.md](reference.md) for detailed documentation
3. See the main [CLAUDE.md](../../../CLAUDE.md) for project guidelines

## Version

- Created: 2026-01-07
- Last updated: 2026-01-07
- Compatible with: Claude Code CLI

## License

Same as parent project (spotfm).
