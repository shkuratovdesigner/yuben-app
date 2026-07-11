# YuBen — local dev orchestration. Run `make help` for the command list.
.DEFAULT_GOAL := help

FRONTEND := frontend
BACKEND  := backend
PY       := $(BACKEND)/.venv/bin/python
PIP      := $(BACKEND)/.venv/bin/pip

.PHONY: help install install-backend install-frontend dev dev-live dev-backend \
        dev-frontend dev-frontend-live build typecheck test test-backend fixtures clean

help:
	@echo "YuBen dev commands:"
	@echo "  make install     Create backend venv + install frontend node deps"
	@echo "  make dev         Run backend (:8000) + frontend (:5173) — frontend in MOCK mode"
	@echo "  make dev-live    Run backend + frontend in LIVE mode (VITE_USE_MOCKS=0)"
	@echo "  make build       Production build of the frontend (tsc -b && vite build)"
	@echo "  make test        Backend pytest + frontend typecheck"
	@echo "  make fixtures    Regenerate contract fixtures from data/*.json"

install: install-backend install-frontend

install-backend:
	python3 -m venv $(BACKEND)/.venv
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

# Regenerate research-result.*.json (+ progress/adapters/history/config) fixtures.
fixtures:
	$(PY) contracts/build_fixtures.py

clean:
	rm -rf $(FRONTEND)/dist $(FRONTEND)/node_modules/.vite
