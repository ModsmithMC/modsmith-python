"""Sphinx configuration."""

import re

from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

import modsmith

project = "Modsmith"
release = modsmith.__version__
author = "YufengPeng"
copyright = "2026, YufengPeng"  # noqa: A001

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
]
exclude_patterns = ["_build", "_theme", "assets"]

html_theme = "modsmith"
html_theme_path = ["_theme"]
html_title = project
html_favicon = "assets/logo.svg"
html_static_path = ["assets"]
html_permalinks_icon = "#"
html_show_sourcelink = False
toc_object_entries_show_parents = "hide"

# Single backticks in docstrings refer to objects.
default_role = "py:obj"
nitpicky = True

autodoc_default_options = {"exclude-members": "model_config"}
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
napoleon_numpy_docstring = False
python_use_unqualified_type_names = True
doctest_global_setup = "from modsmith.minecraft import maven_path"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/stable", None),
}


def resolve_short_name(
    app: Sphinx, env: BuildEnvironment, node, contnode
) -> object | None:
    """Link a short name, or a name in a private module, to its public object."""
    if node.get("refdomain") != "py":
        return None
    parts = str(node["reftarget"]).split(".")
    suffix = ".".join(part for part in parts if not part.startswith("_"))
    domain = env.get_domain("py")
    matches = [
        name
        for name in domain.objects  # type: ignore[attr-defined]
        if "._" not in name and (name == suffix or name.endswith(f".{suffix}"))
    ]
    if len(matches) != 1:
        return None
    return domain.resolve_xref(
        env, node["refdoc"], app.builder, "obj", matches[0], node, contnode
    )


def shorten_signature(
    app: Sphinx, what, name, obj, options, signature, return_annotation
) -> tuple[str | None, str | None]:
    """Hide default URLs, which only make signatures harder to read."""
    if signature is None:
        return None, return_annotation
    return re.sub(r"='https?://[^']*'", "=...", signature), return_annotation


def setup(app: Sphinx) -> None:
    """Register the build hooks."""
    app.connect("missing-reference", resolve_short_name)
    app.connect("autodoc-process-signature", shorten_signature)
