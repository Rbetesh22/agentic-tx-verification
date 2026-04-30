PYTHON := .venv/bin/python
TRACKER_PORT ?= 9000
NODE_ADDR ?= 127.0.0.1:9001
TRACKER_ADDR ?= 127.0.0.1:$(TRACKER_PORT)

.PHONY: help setup install test testv test-network demo dashboard tracker node clean

help:
	@echo "Targets:"
	@echo "  make setup        - create .venv and install dependency"
	@echo "  make install      - install dependency into existing .venv"
	@echo "  make test         - run full test suite"
	@echo "  make testv        - run full test suite (verbose)"
	@echo "  make test-network - run only P2P network tests"
	@echo "  make demo         - run demo scenario"
	@echo "  make dashboard    - start web dashboard on http://127.0.0.1:8080"
	@echo "  make tracker      - start tracker server"
	@echo "  make node         - start node (override NODE_ADDR/TRACKER_ADDR)"
	@echo "  make clean        - remove cache artifacts"

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install cryptography pytest

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install cryptography pytest

test:
	$(PYTHON) -m pytest -q

testv:
	$(PYTHON) -m pytest -v

test-network:
	$(PYTHON) -m pytest -q tests/test_network.py

demo:
	$(PYTHON) demo.py

dashboard:
	$(PYTHON) dashboard_server.py

tracker:
	$(PYTHON) tracker.py --port $(TRACKER_PORT)

node:
	$(PYTHON) node.py --addr $(NODE_ADDR) --tracker $(TRACKER_ADDR)

clean:
	rm -rf .pytest_cache __pycache__ tests/__pycache__
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
