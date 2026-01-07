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
2. ✅ Checks if branch is up-to-date (skips rebase if not needed)
3. ✅ Creates feature branch if on main/master
4. ✅ Handles unstaged changes during rebase
5. ✅ Rebases feature branch on base branch (non-interactive)
6. ✅ Shows modified/untracked files for selection
7. ✅ Scans for leaked credentials/secrets (improved pattern matching)
8. ✅ Runs pre-commit hooks (only on staged files)
9. ✅ Runs test suite (with option to skip for docs-only changes)
10. ✅ Handles test failures in unstaged code gracefully
11. ✅ Generates concise commit message
12. ✅ Generates PR description
13. ✅ Creates draft PR on GitHub
14. ✅ Cleans up temporary files

## Key Features

### Safety First
- **Never uses `git add --all`** - Files are selected interactively
- **Improved secret detection** - Smarter pattern matching to reduce false positives
- **Pre-commit validation** - Runs only on staged files (prevents false failures)
- **Smart test handling** - Distinguishes between failures in staged vs unstaged code
- **Skip tests for docs** - Option to skip test suite for documentation-only changes
- **Draft PRs** - PRs created as drafts for review

### Smart File Selection
- Automatically excludes temp files (.DS_Store, *.pyc, etc.)
- Respects .gitignore patterns
- Only suggests untracked files if related to changes
- Filters out cache directories and build artifacts

### Non-Interactive Mode
- Uses `GIT_EDITOR=true` for git operations (compatible with all git versions)
- No interactive prompts during git rebase
- User interaction through Claude's `AskUserQuestion` tool
- Fully automated workflow
- Handles unstaged changes gracefully during rebase

### Comprehensive Validation
- Security checks for leaked credentials (with false positive filtering)
- Pre-commit hooks on staged files only (formatting, linting, type checking)
- Full test suite execution (with smart handling of failures)
- Option to skip tests for documentation-only changes
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
Improved pattern matching for:
- Assignment patterns: `password = "value"`, `api_key: "secret"`
- Secret prefixes: `sk_live_`, `pk_live_`, `ghp_`, `gho_`, `AKIA`
- Private keys: `-----BEGIN PRIVATE KEY-----`
- AWS credentials
- Database URLs with credentials
- Filters out false positives from documentation and code examples

### Validation Pipeline
1. **Security check** - Scan staged files for secrets (filters false positives)
2. **Pre-commit** - Run hooks only on staged files, stage fixes if needed
3. **Tests** - Run full test suite (skip option for docs-only)
4. **Test analysis** - Distinguish failures in staged vs unstaged code
5. **Coverage** - Verify ≥90% for modified modules

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
- ✅ Branch already up-to-date (skip rebase)
- ⚠️ Unstaged changes during rebase (inform user, offer options)
- ❌ Rebase conflicts (abort and exit)
- ⚠️ Secrets detected (review for false positives, confirm before blocking)
- ❌ Pre-commit failures on staged files (show errors, allow fixes)
- ⚠️ Test failures in unstaged code (warn but allow proceeding with confirmation)
- ❌ Test failures in staged code (require fixes)
- ❌ gh CLI not installed (show installation instructions)
- ❌ gh not authenticated (show setup steps)
- ✅ Documentation-only changes (offer to skip tests)

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

## What's New

### Version 2 (2026-01-07)
- ✨ Improved rebase handling with branch status check
- ✨ Removed `--no-edit` flag for better git compatibility
- ✨ Smarter security scanning with reduced false positives
- ✨ Pre-commit runs only on staged files (prevents false failures)
- ✨ Intelligent test failure handling (staged vs unstaged code)
- ✨ Option to skip tests for documentation-only changes
- ✨ Better error handling for unstaged changes during rebase
- ✨ Enhanced gh CLI validation with specific error messages

### Version 1 (2026-01-07)
- Initial release with automated PR creation workflow

## Version

- Created: 2026-01-07
- Last updated: 2026-01-07
- Compatible with: Claude Code CLI

## License

Same as parent project (spotfm).
