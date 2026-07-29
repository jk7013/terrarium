PYTHON ?= python3
TEST_COMPOSE = docker compose -f docker-compose.test.yml

.PHONY: check lint test test-docker retrieval-baseline retrieval-baseline-resume retrieval-check retrieval-check-resume

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

retrieval-baseline:
	$(PYTHON) scripts/retrieval_baseline.py capture

retrieval-baseline-resume:
	$(PYTHON) scripts/retrieval_baseline.py capture --resume

retrieval-check:
	$(PYTHON) scripts/retrieval_baseline.py check \
		--candidate-output /tmp/terrarium-retrieval-candidate.json

retrieval-check-resume:
	$(PYTHON) scripts/retrieval_baseline.py check \
		--candidate-output /tmp/terrarium-retrieval-candidate.json \
		--resume
