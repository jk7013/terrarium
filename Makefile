PYTHON ?= python3
TEST_COMPOSE = docker compose -f docker-compose.test.yml

.PHONY: check lint test test-docker

check: lint test

lint:
	$(PYTHON) -m compileall -q app tests scripts
	$(PYTHON) -m ruff check app tests scripts --select E9,F63,F7,F82

test:
	$(PYTHON) -m pytest -q -m "not integration"

test-docker:
	@status=0; \
	$(TEST_COMPOSE) up --build --abort-on-container-exit --exit-code-from terrarium-tests || status=$$?; \
	$(TEST_COMPOSE) down --volumes --remove-orphans; \
	exit $$status
