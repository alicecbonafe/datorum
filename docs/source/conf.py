import os
import sys
sys.path.insert(0, os.path.abspath("../src"))

project = 'Datorum'
copyright = '2026, Alice Bonafé'
author = 'Alice Bonafé'

version = '0.1.0a2'
release = '0.1.0a2'

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "sphinxcontrib.autodoc_pydantic",
    "myst_parser",
]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autodoc_member_order = "bysource"

autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_field_summary = True
autodoc_pydantic_field_list_validators = False
autodoc_pydantic_field_signature_prefix = "field"

html_theme = "furo"

# This is needed for CI, due to a known bug in Sphinx
# https://github.com/sphinx-doc/sphinx/issues/14223
# TODO Monitor the fix for the Sphinx issue and remove this statement when appropriate.
suppress_warnings = ["ref.python"]
