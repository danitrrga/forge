VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
.PHONY: test dist publish
test:
	python3 -m unittest discover -s tests -q
dist:
	python3 scripts/build.py
publish: dist
	scripts/upload.sh dist/acme_dates-$(VERSION).tar.gz
