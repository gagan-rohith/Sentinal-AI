PYTHON ?= python

.PHONY: install data run test lint format typecheck check

install:
	$(PYTHON) -m pip install -e ".[dev]"

data:
	$(PYTHON) -m data.generate_data

run:
	$(PYTHON) -m uvicorn app.main:app --reload --port 8000

test:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

typecheck:
	$(PYTHON) -m mypy .

check: lint typecheck test
