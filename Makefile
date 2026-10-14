PYTHON ?= python3
VENV_PYTHON := .venv/bin/python

.PHONY: setup test verify db-upgrade run

setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[test]"

test:
	$(VENV_PYTHON) -m pytest

verify: test
	$(VENV_PYTHON) -m alembic upgrade head

db-upgrade:
	$(VENV_PYTHON) -m alembic upgrade head

run: db-upgrade
	$(VENV_PYTHON) -m uvicorn app.main:app --reload
