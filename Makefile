PYTHON ?= python

.PHONY: install data index bench demo run test lint format typecheck check up down logs

install:
	$(PYTHON) -m pip install -e ".[dev]"

data:
	$(PYTHON) -m data.generate_data

index:
	$(PYTHON) -m retrieval.indexing --if-stale

bench:
	$(PYTHON) -m evals.benchmark

# Terminal walkthrough of INC-1060. ARGS=--memory skips Elasticsearch, ARGS="--pause 2" slows it for recording.
demo:
	$(PYTHON) -m app.demo $(ARGS)

run:
	$(PYTHON) -m uvicorn --factory app.main:create_app --reload --port 8000

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

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api
