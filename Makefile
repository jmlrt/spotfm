VERSION := $(shell uv run hacks/get_version.py)

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
