VERSION := $(shell uv run hacks/get_version.py)

.PHONY: help
help:
	@echo "spotfm Makefile - Available targets:"
	@echo ""
	@echo "Setup:"
	@echo "  install              Install dependencies (creates .venv)"
	@echo "  add PACKAGE=name     Add a new package dependency"
	@echo "  remove PACKAGE=name  Remove a package dependency"
	@echo ""
	@echo "Code Quality:"
	@echo "  format               Format code with ruff"
	@echo "  lint                 Check code with ruff"
	@echo "  lint-fix             Auto-fix linting issues"
	@echo "  lint-fix-unsafe      Auto-fix including unsafe fixes"
	@echo "  pre-commit           Run all pre-commit hooks"
	@echo ""
	@echo "Testing:"
	@echo "  test                 Run all tests (unit + integration)"
	@echo "  test-unit            Run unit tests only (fast)"
	@echo "  test-integration     Run integration tests only"
	@echo "  test-verbose         Run tests with verbose output"
	@echo "  test-coverage        Run tests with coverage report (HTML in htmlcov/)"
	@echo "  test-parallel        Run tests in parallel (faster)"
	@echo "  test-watch           Watch for changes and re-run tests"
	@echo "  test-failed          Re-run only failed tests"
	@echo "  test-all-versions    Test across supported Python versions (3.14+)"
	@echo ""
	@echo "CLI Commands:"
	@echo "  dupes-ids            Find duplicate track IDs (console output)"
	@echo "  dupes-names          Find similar track names via fuzzy matching"
	@echo "  dupes-ids-csv        Export duplicate IDs to data/dupes_ids.csv"
	@echo "  dupes-names-csv      Export similar tracks to data/dupes_names.csv"
	@echo "  relinked             Find relinked tracks (console output)"
	@echo "  relinked-csv         Export relinked tracks to data/relinked_tracks.csv"
	@echo ""
	@echo "Build & Publish:"
	@echo "  build                Build distribution packages"
	@echo "  clean                Remove build artifacts, .venv, and cache"
	@echo "  publish              Tag release, push, and upload to PyPI"

.PHONY: sync
sync:
	uv sync --all-extras

.PHONY: install
install: sync

.PHONY: add
add:
	@echo "Usage: make add PACKAGE=<package-name>"
	@test -n "$(PACKAGE)" && uv add $(PACKAGE) || true

.PHONY: remove
remove:
	@echo "Usage: make remove PACKAGE=<package-name>"
	@test -n "$(PACKAGE)" && uv remove $(PACKAGE) || true

.PHONY: pre-commit
pre-commit:
	uv run pre-commit run --all-files

.PHONY: format
format:
	uv run ruff format .

.PHONY: lint
lint:
	uv run ruff check .

.PHONY: lint-fix
lint-fix:
	uv run ruff check --fix .

.PHONY: lint-fix-unsafe
lint-fix-unsafe:
	uv run ruff check --fix --unsafe-fixes .

.PHONY: test
test:
	uv run pytest

.PHONY: test-unit
test-unit:
	uv run pytest -m unit

.PHONY: test-integration
test-integration:
	uv run pytest -m integration

.PHONY: test-verbose
test-verbose:
	uv run pytest -vv

.PHONY: test-coverage
test-coverage:
	uv run pytest --cov=spotfm --cov-report=html --cov-report=term

.PHONY: test-parallel
test-parallel:
	uv run pytest -n auto

.PHONY: test-watch
test-watch:
	uv run pytest-watch

.PHONY: test-failed
test-failed:
	uv run pytest --lf

.PHONY: test-all-versions
test-all-versions:
	@echo "Testing with Python 3.14 (only supported version)..."
	@echo ""
	@echo "========================================"; \
	echo "Testing with Python 3.14..."; \
	echo "========================================"; \
	uv sync --python=3.14 --all-extras --quiet && \
	uv run --python=3.14 pytest -q --tb=line || exit 1
	@echo ""
	@echo "✅ Python 3.14 passed!"

.PHONY: dupes-ids
dupes-ids:
	uv run spfm spotify find-duplicate-ids

.PHONY: dupes-names
dupes-names:
	uv run spfm spotify find-duplicate-names

.PHONY: dupes-ids-csv
dupes-ids-csv:
	uv run spfm spotify find-duplicate-ids -o data/dupes_ids.csv

.PHONY: dupes-names-csv
dupes-names-csv:
	uv run spfm spotify find-duplicate-names -o data/dupes_names.csv

.PHONY: relinked
relinked:
	uv run spfm spotify find-relinked-tracks

.PHONY: relinked-csv
relinked-csv:
	uv run spfm spotify find-relinked-tracks -o data/relinked_tracks.csv

.PHONY: build
build:
	rm -fr build/* dist/*
	uv build

.PHONY: clean
clean:
	rm -fr build dist .venv *.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type d -name __pycache__ -delete

.PHONY: publish
publish: install build
	git pull origin main
	git tag -m "v$(VERSION)" v$(VERSION)
	git push --tags
	uv run twine upload -u __token__ dist/*
