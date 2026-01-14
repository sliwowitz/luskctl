.PHONY: lint format test check install install-dev clean

# Run linter and format checker (fast, run before commits)
lint:
	poetry run ruff check .
	poetry run ruff format --check .

# Auto-fix lint issues and format code
format:
	poetry run ruff check --fix .
	poetry run ruff format .

# Run tests with coverage
test:
	poetry run pytest --cov=luskctl --cov-report=term-missing

# Run all checks (equivalent to CI)
check: lint test

# Install runtime dependencies only
install:
	poetry install --only main

# Install all dependencies (dev, test, docs)
install-dev:
	poetry install --with dev,test,docs

# Build documentation locally
docs:
	poetry run mkdocs serve

# Build documentation for deployment
docs-build:
	poetry run mkdocs build

# Clean build artifacts
clean:
	rm -rf dist/ site/ .coverage coverage.xml .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
