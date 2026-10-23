.PHONY: lint test

lint:
	@echo lint >> gate.log
	@python3 -m py_compile labels/*.py tests/*.py && echo "lint ok"

test:
	@echo test >> gate.log
	@python3 -m unittest discover -s tests -t .
