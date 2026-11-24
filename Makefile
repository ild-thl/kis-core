# askFrancis test runner. Run `make` or `make help` for the list of targets.
#
# Two fast UNIT suites (no live stack needed):
#   - backend  : pytest INSIDE the askf-backend container (local Python is too old
#                — the code needs 3.10+, the container ships 3.11). The default
#                run passes -m "not e2e", so live RAG-eval tests are skipped.
#   - frontend : Vitest on the host (pure-logic units, node environment).
# Slow E2E suites (need the live stack up):
#   - backend  : live RAG-eval tests marked @e2e — `make test-backend-e2e`.
#   - frontend : Playwright on the host — `make test-e2e` (frontend :3000, backend :8000).

BACKEND_CONTAINER ?= askf-backend

.DEFAULT_GOAL := help
.PHONY: help test test-backend test-backend-e2e test-frontend test-unit test-e2e test-all

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

test: test-unit ## Alias for test-unit (the fast default suites)

test-unit: ## Run both fast unit suites (backend + frontend), no live stack needed
	@$(MAKE) test-backend
	@$(MAKE) test-frontend

test-backend: ## Run fast backend pytest in the container (excludes live @e2e). Pass args via ARGS=...
	@docker ps --format '{{.Names}}' | grep -qx $(BACKEND_CONTAINER) \
		|| { echo "✗ $(BACKEND_CONTAINER) is not running. Start the stack first (docker compose up -d)."; exit 1; }
	docker exec $(BACKEND_CONTAINER) python -m pytest tests/ -m "not e2e" $(ARGS)

test-backend-e2e: ## Run the live backend RAG-eval suites (@e2e). Needs the stack up + eval data ingested.
	@docker ps --format '{{.Names}}' | grep -qx $(BACKEND_CONTAINER) \
		|| { echo "✗ $(BACKEND_CONTAINER) is not running. Start the stack first (docker compose up -d)."; exit 1; }
	docker exec $(BACKEND_CONTAINER) python -m pytest tests/ -m e2e $(ARGS)

test-frontend: ## Run frontend Vitest unit tests on the host
	cd frontend && npm test

test-e2e: ## Run frontend Playwright E2E tests (needs the live stack up)
	cd frontend && npm run test:e2e -- $(ARGS)

test-all: ## Run all unit suites (backend + frontend), then E2E
	@$(MAKE) test-unit
	@$(MAKE) test-e2e
