VENV := venv
PYTHON := $(VENV)/bin/python

$(PYTHON):
	virtualenv $(VENV) --python python3.11

.PHONY: pip
pip: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip build

.PHONY: pre-commit
pre-commit:
	pre-commit run --all-files

.PHONY: build
build: $(PYTHON)
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
