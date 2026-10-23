.PHONY: lint unit templates e2e visual load check

lint:
	@echo lint >> gate.log; [ -d .git ] && echo lint >> .git/gate.log || true
	@python3 -m py_compile notify/*.py scripts/*.py && echo "lint ok"

unit:
	@echo unit >> gate.log; [ -d .git ] && echo unit >> .git/gate.log || true
	@python3 -m unittest discover -s tests -t .

templates:
	@python3 scripts/check_templates.py

e2e:
	@python3 scripts/suite.py e2e

visual:
	@python3 scripts/suite.py visual

load:
	@python3 scripts/suite.py load

check: lint unit templates e2e visual load
