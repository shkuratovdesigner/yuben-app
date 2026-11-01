# YuBen — local dev orchestration. Run `make help` for the command list.
#
# A thin wrapper: every step lives in yuben.py (standard library, runs on any
# Python 3.9+) so macOS, Linux and Windows share one implementation. Windows has
# no make; run `py yuben.py <command>` there, or double-click start.cmd.
.DEFAULT_GOAL := help

# Any Python runs the launcher; it finds a 3.10+ for the backend venv itself.
LAUNCHER ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null)
YUBEN    := $(LAUNCHER) yuben.py
# The venv interpreter, for the contract scripts below (Unix layout — make is
# not used on Windows).
PY       := backend/.venv/bin/python

# Build the venv from a specific interpreter: make install PYTHON=/path/to/python3.12
PYTHON ?=

.PHONY: help install start dev build typecheck test test-backend fixtures \
        validate-fixtures clean

help:
	@echo "YuBen dev commands (each is also: python yuben.py <command>):"
	@echo "  make install     Create backend venv + install frontend node deps"
	@echo "  make start       Build, then serve the whole app on :8000 (next free port if busy)"
	@echo "  make dev         Run backend + frontend (:5173) with hot reload"
	@echo "  make build       Production build of the frontend (tsc -b && vite build)"
	@echo "  make test        Backend pytest + frontend typecheck"
	@echo "  make fixtures    Rebuild demo fixtures from contracts/mock_videos/, then validate"
	@echo "  make validate-fixtures  Contract-check the committed fixtures"
	@echo "Set YUBEN_PORT to pin the backend port."

install:
	$(YUBEN) install $(if $(PYTHON),--python $(PYTHON))

start:
	$(YUBEN) start

dev:
	$(YUBEN) dev

build:
	$(YUBEN) build

typecheck:
	cd frontend && npx tsc -b

test:
	$(YUBEN) test

test-backend:
	$(YUBEN) test --backend-only

# Rebuild the demo fixtures from the curated video set, then contract-check them.
fixtures:
	$(PY) contracts/build_mock_fixtures.py
	$(PY) contracts/validate_fixtures.py

# Contract-check the committed fixtures without rebuilding them.
validate-fixtures:
	$(PY) contracts/validate_fixtures.py

clean:
	rm -rf frontend/dist frontend/node_modules/.vite
