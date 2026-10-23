.PHONY: css unit visual visual-update e2e api-contract check

css:
	@python3 scripts/css_lint.py

unit:
	@echo unit >> gate.log; [ -d .git ] && echo unit >> .git/gate.log || true
	@python3 -m unittest discover -s tests -t .

visual:
	@python3 scripts/visual.py

visual-update:
	@python3 scripts/visual.py --update

e2e:
	@python3 scripts/suite.py e2e

api-contract:
	@python3 scripts/suite.py api-contract

check: css unit visual e2e api-contract
