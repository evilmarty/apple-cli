PYTHON ?= python3
BUILD_VENV ?= .venv-build

.PHONY: build test clean

build:
	$(PYTHON) -m venv $(BUILD_VENV)
	$(BUILD_VENV)/bin/python -m pip install --quiet --upgrade pip build
	$(BUILD_VENV)/bin/python -m build

test:
	$(PYTHON) -m unittest discover -s tests

clean:
	rm -rf build dist *.egg-info $(BUILD_VENV)
