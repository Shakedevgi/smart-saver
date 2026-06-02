.PHONY: setup dev dev-local dev-sim test clean

PYTHON = venv/bin/python
PIP    = venv/bin/pip

setup:
	python3 -m venv venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev:
	$(PYTHON) run_dev.py

dev-local:
	$(PYTHON) run_dev.py --local

dev-sim:
	$(PYTHON) run_dev.py --simulator

test:
	$(PYTHON) tests/test_smoke.py

clean:
	rm -rf data/tmp/*
