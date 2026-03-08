# Contributing to spotfm

Thank you for your interest in contributing to spotfm! This guide will help you get started.

## Getting Started

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/jmlrt/spotfm.git
cd spotfm

# Install dependencies
make install

# Verify setup
make check  # Runs lint, typecheck, and tests
```

### Understand the Project

Before contributing, please read:
1. [CLAUDE.md](CLAUDE.md) - Architecture and code guidance
2. [README.md](README.md) - Project overview and usage
3. [TODO.md](TODO.md) - Planned features and roadmap

## Development Workflow

### 1. Create a Feature Branch

```bash
# Branch naming: feature/, bugfix/, docs/, test/, refactor/
git checkout -b feature/your-feature-name
```

### 2. Make Changes

Follow these practices:

- **One change per commit**: Each commit should be atomic and pass `make check`
- **Test-driven development**: Write tests before or alongside code
- **Run quality checks**: Before committing, run `make check`

```bash
# During development
make test           # Quick test run
make format         # Auto-fix code style
make lint           # Check for issues
make typecheck      # Type checking
make check          # Full quality check (run before commit!)
```

### 3. Commit Changes

Write clear, focused commit messages:

```
Brief summary (50 chars or less)

- Key change 1
- Key change 2
- Key change 3

Co-Authored-By: Your Name <your.email@example.com>
```

**Guidelines:**
- Be concise (focus on "what" and "why", not "how")
- Use bullet points for related changes
- Mention test coverage improvements if significant
- Link to issues or PRs if applicable

### 4. Test Your Changes

Before submitting a PR:

```bash
# Run full quality check
make check

# Run specific test file
uv run pytest tests/test_something.py

# Run tests with coverage
make test-cov

# Test specific functionality
uv run pytest -k "test_name"
```

**Coverage requirement**: All modified or new code must have ≥90% test coverage.

### 5. Submit a Pull Request

1. Push your branch: `git push origin feature/your-feature-name`
2. Open a PR on GitHub targeting `main`
3. Fill in the PR description with:
   - What changes you made
   - Why you made them
   - How to test the changes
4. Ensure all checks pass (GitHub Actions)

## Code Style

The project uses:

- **Language**: Python 3.11+ (uses match/case statements)
- **Formatter**: ruff (120 character line length)
- **Linter**: ruff (checks run via pre-commit hooks)
- **Type checking**: Built-in type hints (Python 3.11+)

### Pre-commit Hooks

Hooks run automatically on `git commit`:

```bash
# Manually run all hooks
make pre-commit

# Or run pre-commit directly
pre-commit run --all-files
```

## Testing

### Test Organization

Tests are in the `tests/` directory with markers:

- `@pytest.mark.unit` - Fast unit tests (default)
- `@pytest.mark.integration` - Tests using databases
- `@pytest.mark.slow` - Long-running tests

### Database Isolation (CRITICAL)

All tests MUST use temporary databases:

```python
def test_example(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
    """Test that interacts with database."""
    from spotfm import utils

    # CRITICAL: Monkeypatch DATABASE to use temp database
    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

    # ... test code
```

### Running Tests

```bash
# Run all tests
make test

# Run only unit tests (fast)
make test-unit

# Run with coverage report
make test-coverage

# Run specific test
uv run pytest tests/test_track.py::TestTrack::test_something
```

## Architecture & Design Decisions

### Critical Patterns

1. **Three-Tier Caching**: Pickle → SQLite → Spotify API
2. **Entity Lifecycle**: `get_*()` → `update_from_cache()` → `update_from_db()` → `update_from_api()` → `sync_to_db()`
3. **Orphaned Tracks**: Never delete (they prevent re-adding removed tracks)
4. **String Sanitization**: Always use `utils.sanitize_string()` for SQL safety

### Before Making Architectural Changes

- Read the [Critical Warnings](CLAUDE.md#critical-warnings-️) in CLAUDE.md
- Check [Key Implementation Notes](CLAUDE.md#key-implementation-notes) for context
- Understand [Track Lifecycle Tracking](README.md#track-lifecycle-tracking) implications

## Common Tasks

### Adding a New Spotify Command

1. Add command implementation to `spotfm/spotify/misc.py`
2. Add CLI wrapper to `spotfm/cli.py` in `spotify_cli()`
3. Add tests to `tests/test_integration.py` or new test file
4. Update README.md with command documentation
5. Add entry to TODO.md if it's a planned feature

### Adding a New Database Table

1. Add migration to `spotfm/sqlite.py` in `migrate_database_schema()`
2. Update schema in `hacks/create-tables.sql` for reference
3. Add table creation SQL in the migration function
4. Update test fixtures in `tests/conftest.py`
5. Add comprehensive tests for the new schema

### Fixing a Bug

Per [CLAUDE.md Development Practices](CLAUDE.md#development-practices):

> When fixing a bug or inconsistency in one CLI command, proactively check ALL similar commands for the same issue before considering the task done.

Don't wait for the user to ask twice—fix it everywhere.

## Reporting Issues

When reporting bugs:

1. **Be specific**: Include exact command, error message, and version
2. **Provide context**: What were you trying to do?
3. **Include logs**: Run with `--info` or `--debug` flags for more details
4. **Suggest fixes**: If you have ideas, share them

## Questions?

- Check [README.md](README.md) for user documentation
- Check [CLAUDE.md](CLAUDE.md) for architecture and patterns
- Check existing issues and PRs on GitHub
- Open an issue to ask questions

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Help others learn
- Celebrate contributions

Thank you for contributing to spotfm! 🎵
