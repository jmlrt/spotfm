# Create PR Skill - Examples

## Basic Examples

### Example 1: Create PR with Default Settings

**User Request:**
```
Create a PR
```

**Skill Actions:**
1. Ask: "Which base branch to target? (default: main)"
2. User: "main" (or just presses enter)
3. Fetch: `git fetch origin`
4. Current branch: `feature/add-duplicate-detection` (already on feature branch)
5. Rebase: `GIT_EDITOR=true git rebase --no-edit origin/main`
6. Show files:
   ```
   Modified:
     M spotfm/spotify/dupes.py
     M tests/test_dupes.py
     M CLAUDE.md

   Untracked:
     ?? TODO.md (related to dupes feature)
   ```
7. Ask: "Stage these files?"
8. User: "Yes, all of them"
9. Stage: `git add spotfm/spotify/dupes.py tests/test_dupes.py CLAUDE.md TODO.md`
10. Security check: ✅ No secrets detected
11. Pre-commit: `make pre-commit` ✅
12. Tests: `make test` ✅ (179 passed, 87% coverage)
13. Generate commit message:
    ```
    Add duplicate detection for tracks

    - Implement fuzzy matching using rapidfuzz library
    - Add exact ID matching for playlist duplicates
    - Include comprehensive test coverage (87%)
    - Update documentation with new commands

    🤖 Generated with [Claude Code](https://claude.com/claude-code)

    Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
    ```
14. Commit: `git commit -F COMMIT_MESSAGE.md`
15. Generate PR description:
    ```markdown
    ## Summary
    - Add duplicate detection feature for tracks across playlists
    - Support both exact ID matching and fuzzy name matching

    ## Changes
    - New module: spotfm/spotify/dupes.py with find_duplicate_ids() and find_duplicate_names()
    - Test coverage: 87% for dupes module
    - CLI commands: spfm spotify find-duplicate-ids/names
    - Documentation updated in CLAUDE.md

    ## Testing
    - Test coverage: 87%
    - Tests added: 12 new tests in test_dupes.py
    - All tests passing: ✅

    ## Checklist
    - [x] Tests added/updated
    - [x] Documentation updated
    - [x] Pre-commit hooks pass
    - [x] No secrets or PII leaked

    🤖 Generated with [Claude Code](https://claude.com/claude-code)
    ```
16. Push: `git push -u origin feature/add-duplicate-detection`
17. Create PR: `gh pr create --base main --head feature/add-duplicate-detection --draft --body-file PR_DESCRIPTION.md`
18. Cleanup: `rm COMMIT_MESSAGE.md PR_DESCRIPTION.md`
19. Success:
    ```
    ✅ Pull Request Created Successfully!

    Branch: feature/add-duplicate-detection
    Base: main
    PR URL: https://github.com/jmlrt/spotfm/pull/12

    Files changed: 4
    Commits: 1
    Tests: All passing (179)
    Coverage: 87%

    Next steps:
    - Review the PR description and edit if needed
    - Request reviewers
    - Mark as ready for review when appropriate
    ```

---

### Example 2: Create PR from Main Branch (New Feature Branch)

**User Request:**
```
Create a PR for the performance improvements
```

**Skill Actions:**
1. Ask: "Base branch? (default: main)"
2. User: "main"
3. Fetch: `git fetch origin`
4. Current branch: `main` (on main branch)
5. Ask: "You're on main. Please provide a feature branch name:"
   Suggest: `feature/performance-improvements` (based on user's request)
6. User: "feature/optimize-api-calls"
7. Create branch: `git checkout -b feature/optimize-api-calls`
8. Rebase: `GIT_EDITOR=true git rebase --no-edit origin/main` (already up to date)
9. [Continue with file selection, security checks, etc.]

---

### Example 3: Custom Base Branch (Release Branch)

**User Request:**
```
Create a PR against the release/v2.0 branch
```

**Skill Actions:**
1. Use base: `release/v2.0` (from user request)
2. Fetch: `git fetch origin`
3. Current branch: `feature/hotfix-auth`
4. Rebase: `GIT_EDITOR=true git rebase --no-edit origin/release/v2.0`
5. [Continue with normal workflow, but targeting release/v2.0 instead of main]

---

## Advanced Examples

### Example 4: Handling Untracked Files

**Scenario:** Mix of related and unrelated untracked files

**Skill Actions:**
```
Found 2 modified files and 5 untracked files:

Modified:
  M spotfm/spotify/track.py
  M tests/test_track.py

Untracked (related to changes):
  ?? PERFORMANCE.md (documents performance improvements)

Untracked (unrelated - suggest skipping):
  ?? notes.txt (personal notes)
  ?? debug.log (debug output)

Untracked (temp - auto-skip):
  ?? .DS_Store
  ?? __pycache__/

Which files should I stage?
```

**User:** "Stage modified and PERFORMANCE.md"

**Result:** Only stages relevant files, skips temp/unrelated files

---

### Example 5: Secret Detection and Recovery

**Scenario:** Accidentally included API key in config file

**Skill Actions:**
1. [File selection, staging]
2. Security check runs:
   ```bash
   git diff --cached | grep -iE "(password|secret|api[_-]?key|token)"
   ```
3. **FOUND:**
   ```
   config.py:42: api_key = "sk_live_abc123xyz789"
   ```
4. **STOP IMMEDIATELY**
5. Unstage: `git reset HEAD config.py`
6. Show user:
   ```
   ⚠️ Security Check Failed!

   Potential secret detected in staged files:
   - File: config.py
   - Line: 42
   - Pattern: api_key = "sk_live_..."

   Action required:
   1. Remove the secret from config.py
   2. Use environment variables instead: api_key = os.getenv("SPOTIFY_API_KEY")
   3. Add config.py to .gitignore if needed
   4. Try creating the PR again

   Process stopped. No changes committed.
   ```

---

### Example 6: Pre-commit Hook Failures

**Scenario:** Code formatting issues detected

**Skill Actions:**
1. [File selection, staging, security check ✅]
2. Run pre-commit:
   ```bash
   make pre-commit
   ```
3. **Output:**
   ```
   ruff format.....................................................Failed
   - hook id: ruff-format
   - files were modified by this hook

   1 file reformatted
   ```
4. Show user:
   ```
   Pre-commit hooks made changes to your files:

   Modified by hooks:
     M spotfm/spotify/track.py (formatting fixed)

   Would you like to:
   1. Review the changes
   2. Stage the fixes and continue
   3. Abort the PR creation
   ```
5. User: "Stage the fixes"
6. Stage: `git add spotfm/spotify/track.py`
7. Re-run pre-commit: `make pre-commit` ✅ (now passes)
8. [Continue with tests, commit, PR]

---

### Example 7: Test Failures

**Scenario:** Introduced a bug that breaks tests

**Skill Actions:**
1. [File selection, staging, security check ✅, pre-commit ✅]
2. Run tests:
   ```bash
   make test
   ```
3. **Output:**
   ```
   FAILED tests/test_track.py::TestTrack::test_get_genres - AssertionError
   179 tests, 1 failed, 178 passed
   ```
4. **STOP**
5. Show user:
   ```
   ❌ Tests Failed!

   Failed tests:
   - tests/test_track.py::TestTrack::test_get_genres

   Error:
   AssertionError: Expected ['rock', 'indie'] but got ['rock']

   Action required:
   1. Fix the failing test or the code
   2. Run tests locally: make test
   3. Try creating the PR again after tests pass

   Process stopped. No changes committed.
   ```

---

### Example 8: Coverage Check

**Scenario:** Modified module has low test coverage

**Skill Actions:**
1. [File selection, staging, security check ✅, pre-commit ✅]
2. Detect modified module: `spotfm/spotify/track.py`
3. Run coverage check:
   ```bash
   uv run pytest tests/test_track.py --cov=spotfm.spotify.track --cov-report=term-missing
   ```
4. **Output:**
   ```
   Coverage: 85%
   Missing lines: 142-156 (new get_artists() method)
   ```
5. **Warning:**
   ```
   ⚠️ Coverage Warning

   Modified module has <90% coverage:
   - Module: spotfm.spotify.track
   - Current coverage: 85%
   - Missing: lines 142-156 (get_artists method)

   Recommendation: Add tests for the new get_artists() method

   Would you like to:
   1. Continue anyway (not recommended)
   2. Cancel and add more tests
   ```
6. User: "Cancel, I'll add tests"
7. **Exit** without creating PR

---

### Example 9: Rebase Conflicts

**Scenario:** Upstream changes conflict with feature branch

**Skill Actions:**
1. Fetch: `git fetch origin`
2. Rebase:
   ```bash
   GIT_EDITOR=true git rebase --no-edit origin/main
   ```
3. **Conflict detected:**
   ```
   CONFLICT (content): Merge conflict in spotfm/spotify/track.py
   ```
4. **Abort rebase:**
   ```bash
   git rebase --abort
   ```
5. Show user:
   ```
   ❌ Rebase Failed - Conflicts Detected

   Your branch has conflicts with origin/main:
   - spotfm/spotify/track.py

   Action required:
   1. Resolve conflicts manually:
      git rebase origin/main
   2. Fix the conflicts in your editor
   3. Mark as resolved:
      git add <resolved-files>
      git rebase --continue
   4. Try creating the PR again

   Process stopped. Working directory unchanged.
   ```

---

## Edge Cases

### Example 10: Empty Changeset

**Scenario:** No changes to commit

**Skill Actions:**
1. Run: `git status --porcelain`
2. **Output:** (empty)
3. Show user:
   ```
   ℹ️ No Changes to Commit

   Your working directory is clean. There are no modified or untracked files to include in a PR.

   If you expected changes:
   1. Check if files are already committed: git log
   2. Check if files are ignored: git status --ignored
   3. Make your changes and try again
   ```

---

### Example 11: Already Up to Date

**Scenario:** Feature branch is already ahead of base

**Skill Actions:**
1. Fetch: `git fetch origin`
2. Check: `git log origin/main..HEAD`
3. **Output:**
   ```
   commit abc123 Add duplicate detection
   ```
4. Show user:
   ```
   ℹ️ Branch Already Has Commits

   Your feature branch is already 1 commit ahead of origin/main:
   - abc123 Add duplicate detection

   Would you like to:
   1. Add more changes to this branch (stage additional files)
   2. Create a PR with existing commits (skip new commit)
   3. Cancel
   ```

---

### Example 12: Using PR Template

**Scenario:** Project has a GitHub PR template

**Skill Actions:**
1. Check for template:
   ```bash
   if [ -f .github/PULL_REQUEST_TEMPLATE.md ]; then
     TEMPLATE_PATH=".github/PULL_REQUEST_TEMPLATE.md"
   fi
   ```
2. **Found template:**
   ```markdown
   ## Description
   [Describe your changes]

   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change

   ## Testing
   [Describe testing performed]

   ## Checklist
   - [ ] Tests pass locally
   - [ ] Documentation updated
   ```
3. Generate PR description following template structure:
   ```markdown
   ## Description
   Added duplicate detection feature for tracks using exact ID matching and fuzzy name matching with rapidfuzz.

   ## Type of Change
   - [ ] Bug fix
   - [x] New feature
   - [ ] Breaking change

   ## Testing
   - Added 12 new tests in test_dupes.py
   - All tests passing (179/179)
   - Coverage: 87% for dupes module

   ## Checklist
   - [x] Tests pass locally
   - [x] Documentation updated

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```

---

## Integration Examples

### Example 13: Full Workflow with Multiple Iterations

**Scenario:** Complete PR creation with hooks fixing issues

**User:** "Create a PR for the new caching feature"

**Workflow:**
1. ✅ Base branch: main
2. ✅ Fetch and rebase
3. ✅ File selection (4 files staged)
4. ✅ Security check passed
5. ❌ Pre-commit failed (formatting issues)
6. ✅ Stage hook fixes
7. ✅ Re-run pre-commit (passed)
8. ✅ Tests passed (179 tests, 92% coverage)
9. ✅ Commit created
10. ✅ PR created (draft)
11. ✅ Cleanup temp files

**Final output:**
```
✅ Pull Request Created Successfully!

Branch: feature/add-caching
Base: main
PR URL: https://github.com/jmlrt/spotfm/pull/13

Files changed: 4
Commits: 1
Tests: All passing (179)
Coverage: 92%

Timeline:
- Pre-commit hooks fixed formatting issues (auto-staged)
- All validation passed on second run

Next steps:
- Review the PR description
- Request reviewers
- Mark as ready when appropriate
```

---

## Troubleshooting Examples

### Example 14: gh CLI Not Installed

**Error:**
```bash
gh pr create --base main --draft --body-file PR_DESCRIPTION.md
# bash: gh: command not found
```

**Skill Response:**
```
❌ GitHub CLI Not Found

The 'gh' command is required to create PRs but is not installed.

Installation:
  macOS:    brew install gh
  Linux:    See https://cli.github.com/
  Windows:  See https://cli.github.com/

After installing:
  gh auth login   # Authenticate with GitHub

Your changes have been committed locally:
  Branch: feature/add-caching
  Commit: abc123

You can create the PR manually:
  1. Push: git push -u origin feature/add-caching
  2. Visit: https://github.com/jmlrt/spotfm/compare
```

---

### Example 15: gh Not Authenticated

**Error:**
```bash
gh pr create: HTTP 401: Bad credentials
```

**Skill Response:**
```
❌ GitHub Authentication Required

The 'gh' CLI is not authenticated.

Setup:
  gh auth login

Then try creating the PR again.

Your changes are committed locally on branch: feature/add-caching
```

---

## Summary

These examples demonstrate:
- ✅ Basic PR creation workflow
- ✅ Handling different branch scenarios
- ✅ File selection and filtering
- ✅ Security checks and secret detection
- ✅ Pre-commit hook handling
- ✅ Test validation
- ✅ Coverage checks
- ✅ Error handling and recovery
- ✅ Edge cases
- ✅ Integration with project templates
- ✅ Troubleshooting common issues

The skill is designed to be:
- **Safe**: Multiple validation checkpoints
- **Interactive**: User control over file selection
- **Automated**: Handles repetitive tasks
- **Informative**: Clear feedback at each step
- **Recoverable**: Graceful error handling
