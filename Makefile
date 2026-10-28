PREFIX ?= $(HOME)/bin
PYTHON ?= python3

.PHONY: install test
install:
	install -d "$(PREFIX)"
	install -m 755 bin/codex-wrapper "$(PREFIX)/codex-wrapper"

test:
	$(PYTHON) -m unittest discover -s tests -v
