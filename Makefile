.PHONY: verify test evaluate judge-check run fixtures

verify:
	./scripts/verify.sh

test:
	PYTHONPATH=src pytest -q

evaluate:
	PYTHONPATH=src python3 scripts/evaluate.py

judge-check:
	./scripts/judge_mode_check.sh

run:
	./scripts/start.sh

fixtures:
	python3 scripts/build_fixtures.py
