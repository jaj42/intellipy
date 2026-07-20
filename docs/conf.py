"""Sphinx configuration for the intellipy documentation."""

import os
import sys
from importlib.metadata import version as package_version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _generate import generate  # noqa: E402  (needs the path insert above)

project = "intellipy"
author = "Jona Joachim"
copyright = "2015-2016 Uday Agrawal, Adewole Oyalowo, Asaad Lab; 2026 Jona Joachim"

try:
    release = package_version("intellipy")
except Exception:  # pragma: no cover - docs can build from a source checkout
    release = "0.1.0"
version = release

extensions = [
    "myst_parser",
    "sphinxcontrib.mermaid",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

exclude_patterns = ["_build", "protocol/_generated/*"]

# -- MyST ------------------------------------------------------------------

myst_enable_extensions = ["deflist", "colon_fence", "substitution"]
myst_heading_anchors = 3

# -- Autodoc ---------------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
napoleon_numpy_docstring = True
napoleon_google_docstring = False
# Render "Attributes" sections as :ivar: fields rather than as separate
# descriptions, which would collide with autodoc's own dataclass members.
napoleon_use_ivar = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

# -- HTML ------------------------------------------------------------------

html_theme = "furo"
html_title = f"intellipy {release}"
html_theme_options = {
    "source_repository": "",
    "navigation_with_keys": True,
}

# -- Generated protocol tables ---------------------------------------------

# Rendered from the package's own nomenclature files on every build, so the
# tables in `protocol/` can never drift from what the codec actually loads.
generate(os.path.dirname(os.path.abspath(__file__)))
