VENV := venv
PYTHON := $(VENV)/bin/python
VERSION := $(shell $(PYTHON) hacks/get_version.py)


$(PYTHON):
	virtualenv $(VENV) --python python3.11

.PHONY: pip
pip: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip build

.PHONY: pre-commit
pre-commit: install
	pre-commit run --all-files

.PHONY: build
build: $(PYTHON)
	rm -fr dist/*
	$(PYTHON) -m build .

.PHONY: install
install: $(PYTHON)
	$(PYTHON) -m pip install --editable .[dev]

.PHONY: freeze
freeze: $(PYTHON)
	$(PYTHON) -m pip freeze > requirements.txt

.PHONY: clean
clean:
	rm -fr dist $(VENV) *.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type d -name __pycache__ -delete

.PHONY: publish
publish: install build
	git pull origin main
	git tag -m "v$(VERSION)" v$(VERSION)
	git push --tags
	$(PYTHON) -m twine upload dist/*
