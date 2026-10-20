PY ?= .venv/bin/python
export PATH := $(HOME/.local/bin):$(HOME/.local/node/bin):$(PATH)

.PHONY: help install install-api install-web install-desktop dev-api dev-worker dev-web dev-desktop \
        test lint typecheck build build-web build-desktop migrate smoke verify clean

help:
	@echo "Auto Backlinker - development commands"
	@echo ""
	@echo "  make install          Install every dependency (api, web, desktop)"
	@echo "  make install-api      Create the python venv and install requirements"
	@echo "  make install-web      npm install in apps/web"
	@echo "  make install-desktop  npm install in apps/desktop"
	@echo "  make dev-api          Run the API with reload on :8000"
	@echo "  make dev-worker       Run the standalone background worker"
	@echo "  make dev-web          Run the Next.js web app on :3000"
	@echo "  make dev-desktop      Run the Tauri desktop app"
	@echo "  make migrate          Apply the database migrations"
	@echo "  make test             Run the backend test suite"
	@echo "  make lint             Run ruff over the backend"
	@echo "  make typecheck        Typecheck the web and desktop clients"
	@echo "  make build            Production build of web + desktop frontend"
	@echo "  make smoke            Run the end-to-end smoke test"
	@echo "  make acceptance       Run the end-to-end acceptance test (full product loop)"
	@echo "  make browser-check    Prove that a real browser submits a form"
	@echo "  make desktop-check    Prove the packaged desktop app starts and keeps its session"
	@echo "  make agent-smoke      Prove the local agent claims and executes a task"
	@echo "  make verify           Run every check (scripts/verify_all.sh)"

install: install-api install-web install-desktop

install-api:
	cd apps/api && ./scripts/bootstrap.sh

install-web:
	cd apps/web && npm install

install-desktop:
	cd apps/desktop && npm install

dev-api:
	cd apps/api && ../../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-worker:
	cd apps/api && ../../$(PY) -m app.workers.runner

dev-web:
	cd apps/web && npm run dev

dev-desktop:
	cd apps/desktop && npm run tauri dev

migrate:
	cd apps/api && ../../$(PY) -m alembic upgrade head

test:
	cd apps/api && ../../$(PY) -m pytest -q

lint:
	cd apps/api && ../../$(PY) -m ruff check app tests scripts

typecheck:
	cd apps/web && npx tsc --noEmit
	cd apps/desktop && npx tsc --noEmit

build: build-web build-desktop

build-web:
	cd apps/web && npm run build

build-desktop:
	cd apps/desktop && npm run build

smoke:
	cd apps/api && ../../$(PY) scripts/smoke_core.py

acceptance:
	./scripts/acceptance.py

browser-check:
	./scripts/check_browser_automation.py

desktop-check:
	cd apps/desktop && ../../$(PY) scripts/check-desktop.py

agent-smoke:
	./scripts/smoke_local_agent.py

verify:
	./scripts/verify_all.sh

clean:
	rm -rf apps/web/.next apps/desktop/dist apps/api/.pytest_cache apps/api/.ruff_cache
	find apps/api -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
