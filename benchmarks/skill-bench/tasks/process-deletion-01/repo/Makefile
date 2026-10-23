.PHONY: check deadcode test
check: deadcode test
deadcode:
	python3 tools/deadcode.py
test:
	python3 -m unittest discover -s tests -q
