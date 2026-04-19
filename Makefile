PYTHON ?= python3
BUILD_VENV ?= .venv-build

.PHONY: build test clean publish

build:
	$(PYTHON) -m venv $(BUILD_VENV)
	$(BUILD_VENV)/bin/python -m pip install --quiet --upgrade pip build
	$(BUILD_VENV)/bin/python -m build

publish: build
	$(BUILD_VENV)/bin/python -m pip install --quiet twine
	$(BUILD_VENV)/bin/twine upload dist/*

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

clean:
	rm -rf build dist *.egg-info $(BUILD_VENV)
