.PHONY: test test-fast test-verbose test-integration test-coverage lint build clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Testing ──────────────────────────────────────────────────────────────────

test:  ## Run all tests
	python -m pytest tests/ -v

test-fast:  ## Run unit tests only (skip slow/integration)
	python -m pytest tests/ -v -m "not slow and not integration"

test-verbose:  ## Run all tests with full output
	python -m pytest tests/ -v -s --tb=long

test-integration:  ## Run integration tests only
	python -m pytest tests/test_integration.py -v

test-coverage:  ## Run tests with coverage report
	python -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html:htmlcov \
		--cov-config=.coveragerc

test-watch:  ## Re-run tests on file changes (requires pytest-watch)
	ptw tests/ -- -v --tb=short

# ── Specific test modules ────────────────────────────────────────────────────

test-core:  ## Test core modules (path, cone, smoothing, waypoint)
	python -m pytest tests/test_snake_path.py tests/test_cone_rotation.py \
		tests/test_tangent_smoothing.py tests/test_coords.py -v

test-drivers:  ## Test camera drivers
	python -m pytest tests/test_drivers.py -v

test-grabbers:  ## Test frame grabbers
	python -m pytest tests/test_grabbers.py -v

test-hiders:  ## Test UI hiders
	python -m pytest tests/test_ui_hiders.py tests/test_hider_impls.py -v

test-web:  ## Test web API endpoints
	python -m pytest tests/test_web_api.py -v

# ── Build ────────────────────────────────────────────────────────────────────

build:  ## Build native RenderDoc bridge
	./renderdoc_ext/build.sh

build-from-source:  ## Build bridge + RenderDoc from source
	./renderdoc_ext/build.sh --from-source

clean:  ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info htmlcov/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# ── Dev ──────────────────────────────────────────────────────────────────────

install:  ## Install dependencies
	pip install -e ".[dev]"

install-dev:  ## Install dev + test dependencies
	pip install -e .
	pip install pytest pytest-cov pybind11

dry-run:  ## Quick dry-run test
	python main.py --dry-run --volume-min -2 0 -2 --volume-max 2 1 2 --spacing 2 -v
