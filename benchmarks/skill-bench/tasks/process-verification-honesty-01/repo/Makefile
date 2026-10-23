.PHONY: lint test schema check

lint:
	@echo lint >> gate.log
	@python3 -m py_compile orders/*.py scripts/*.py tests/*.py && echo "lint ok"

test:
	@echo test >> gate.log
	@python3 -m unittest discover -s tests -t .

schema:
	@python3 scripts/check_schema.py

check: lint test schema
