.PHONY: install test lint format clean

install:
	uv sync

test:
	uv run pytest -v

lint:
	uv run ruff check scripts tests

format:
	uv run ruff format scripts tests
	uv run ruff check --fix scripts tests

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
