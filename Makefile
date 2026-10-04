PREFIX ?= $(HOME)/bin

.PHONY: install
install:
	install -d "$(PREFIX)"
	install -m 755 bin/codex-wrapper "$(PREFIX)/codex-wrapper"
