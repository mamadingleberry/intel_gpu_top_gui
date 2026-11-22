# Convenience wrapper; everything also works without make:
#   packaging/install.sh, packaging/build-deb.sh, python3 -m unittest

PREFIX ?= /usr/local
DESTDIR ?=
PYTHON ?= python3

.PHONY: all install uninstall test run demo deb clean

all:
	@true

install:
	DESTDIR="$(DESTDIR)" PREFIX="$(PREFIX)" packaging/install.sh

uninstall:
	DESTDIR="$(DESTDIR)" PREFIX="$(PREFIX)" packaging/install.sh --uninstall

test:
	$(PYTHON) -m unittest discover -s tests -v

run:
	PYTHONPATH=src $(PYTHON) -m intel_gpu_top_gui

demo:
	PYTHONPATH=src $(PYTHON) -m intel_gpu_top_gui --demo

deb:
	packaging/build-deb.sh

clean:
	rm -rf build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
