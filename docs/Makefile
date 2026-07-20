# Minimal makefile for Sphinx documentation.
#
#   make -C docs html      # build into docs/_build/html
#   make -C docs clean
#
# From a uv checkout, prefer:
#   uv run --extra docs sphinx-build -b html docs docs/_build/html

SPHINXOPTS    ?= -W --keep-going
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help clean Makefile

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean:
	rm -rf "$(BUILDDIR)" protocol/_generated

%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
