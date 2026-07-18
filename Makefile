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

.PHONY: help install install-backend install-frontend dev dev-live dev-backend \
        dev-frontend dev-frontend-live build typecheck test test-backend fixtures \
        validate-fixtures clean

help:
	@echo "YuBen dev commands:"
	@echo "  make install     Create backend venv + install frontend node deps"
	@echo "  make dev         Run backend (:8000) + frontend (:5173) — frontend in MOCK mode"
	@echo "  make dev-live    Run backend + frontend in LIVE mode (VITE_USE_MOCKS=0)"
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

# Runs both dev servers in parallel; Ctrl-C stops both.
# `dev`      = frontend in MOCK mode (fixtures, no backend needed).
# `dev-live` = frontend in LIVE mode (VITE_USE_MOCKS=0) → talks to the real backend.
dev:
	@echo "Starting backend :8000 + frontend :5173 [MOCKS] (Ctrl-C to stop)…"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-live:
	@echo "Starting backend :8000 + frontend :5173 [LIVE] (Ctrl-C to stop)…"
	@$(MAKE) -j2 dev-backend dev-frontend-live

dev-backend:
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && npm run dev

dev-frontend-live:
	cd $(FRONTEND) && npm run dev:live

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
