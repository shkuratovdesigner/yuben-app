# YuBen — local dev orchestration. Run `make help` for the command list.
.DEFAULT_GOAL := help

FRONTEND := frontend
BACKEND  := backend
PY       := $(BACKEND)/.venv/bin/python
PIP      := $(BACKEND)/.venv/bin/pip

# The backend needs Python 3.10+ (fastapi 0.139 dropped 3.9). macOS still ships
# 3.9 as `python3`, so pick the newest suitable interpreter on PATH instead of
# assuming. Override with: make install PYTHON=/path/to/python3.12
PYTHON ?= $(shell for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$p >/dev/null 2>&1 \
	  && $$p -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null \
	  && echo $$p && break; \
	done)

.PHONY: help install install-backend install-frontend dev dev-backend \
        dev-frontend start build typecheck test test-backend fixtures \
        validate-fixtures clean

help:
	@echo "YuBen dev commands:"
	@echo "  make install     Create backend venv + install frontend node deps"
	@echo "  make start       Build, then serve the whole app on :8000 — one process"
	@echo "  make dev         Run backend (:8000) + frontend (:5173) — hot reload"
	@echo "  make build       Production build of the frontend (tsc -b && vite build)"
	@echo "  make test        Backend pytest + frontend typecheck"
	@echo "  make fixtures    Rebuild demo fixtures from contracts/mock_videos/, then validate"
	@echo "  make validate-fixtures  Contract-check the committed fixtures"

install: install-backend install-frontend

install-backend:
	@if [ -z "$(PYTHON)" ]; then \
		echo "No Python 3.10+ found on PATH — the backend needs it (fastapi 0.139+)."; \
		echo "macOS ships 3.9 as python3, so you may have to install a newer one."; \
		echo "Already have one elsewhere? Point at it:"; \
		echo "    make install PYTHON=/path/to/python3.12"; \
		exit 1; \
	fi
	@echo "Backend venv using $(PYTHON) ($$($(PYTHON) --version 2>&1))"
	$(PYTHON) -m venv $(BACKEND)/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND)/requirements.txt

install-frontend:
	cd $(FRONTEND) && npm install

# Runs both dev servers in parallel; Ctrl-C stops both. There is one mode: the
# real app. The frontend always talks to the backend, and the bundled example run
# is seeded into the backend's store so a fresh install still has something to
# open before any quota is spent.
dev:
	@echo "Starting backend :8000 + frontend :5173 (Ctrl-C to stop)…"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && npm run dev

# Real use: one process, one URL. The frontend is compiled to static files and
# served by the backend itself, so there is no Node process and no proxy hop —
# just http://localhost:8000. Port 8000 is not configurable here on purpose: the
# same-origin guard's allowlist (backend/app/security.py) names it, so serving
# the SPA elsewhere would 403 every state-changing request.
#
# YUBEN_SERVE_SPA is what makes the backend serve the build, and this is the only
# place that sets it — under `make dev` the backend stays a JSON API even if a
# dist/ is lying around, so :8000 can never answer with a stale UI.
start: build
	@echo "YuBen on http://localhost:8000 (Ctrl-C to stop)…"
	cd $(BACKEND) && YUBEN_SERVE_SPA=1 .venv/bin/uvicorn app.main:app --port 8000

build:
	cd $(FRONTEND) && npm run build

typecheck:
	cd $(FRONTEND) && npx tsc -b

test: test-backend typecheck

test-backend:
	cd $(BACKEND) && .venv/bin/pytest

# Rebuild the demo fixtures from the curated video set, then contract-check them.
fixtures:
	$(PY) contracts/build_mock_fixtures.py
	$(PY) contracts/validate_fixtures.py

# Contract-check the committed fixtures without rebuilding them.
validate-fixtures:
	$(PY) contracts/validate_fixtures.py

clean:
	rm -rf $(FRONTEND)/dist $(FRONTEND)/node_modules/.vite
