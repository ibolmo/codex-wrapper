PYTHON ?= uv run --no-project --with-editable . python

.PHONY: install test
install:
	uv tool install .

test:
	$(PYTHON) -m unittest discover -s tests -v
