"""Sphinx configuration."""

import dataclasses
import inspect
import re
from pathlib import Path
from urllib.parse import urljoin

from pygments.lexers.python import PythonLexer
from pygments.token import Name
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

import modsmith

project = "Modsmith"
release = modsmith.__version__
author = "YufengPeng"
copyright = "2026 YufengPeng"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
]
exclude_patterns = ["_build", "_templates", "_theme", "assets"]

html_theme = "modsmith"
html_theme_path = ["_theme"]
html_title = project
html_baseurl = "https://papa-jun.github.io/ModSmith/"
html_additional_pages = {"404": "404.html"}
html_theme_options = {"base_url": html_baseurl}
html_favicon = "assets/logo.svg"
html_static_path = ["assets"]
html_permalinks_icon = "#"
html_show_sourcelink = False
toc_object_entries_show_parents = "hide"

# Single backticks in docstrings refer to objects.
default_role = "py:obj"
nitpicky = True
nitpick_ignore_regex = [
    ("py:class", r".*\._[A-Z].*"),
    ("py:class", r".*\[.*"),
    ("py:obj", r"typing\.Literal.*"),
]
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

autodoc_default_options = {"exclude-members": "model_config"}
autodoc_member_order = "bysource"
autodoc_typehints = "both"
autosummary_generate = True
add_module_names = False
# Every signature lists one parameter per line.
python_maximum_signature_line_length = 1
templates_path = ["_templates"]
autodoc_typehints_description_target = "documented"
napoleon_numpy_docstring = False
python_use_unqualified_type_names = True
doctest_global_setup = "from modsmith.minecraft import maven_path"

SECTIONS = {
    "get-started": "Get started",
    "guides": "Guides",
    "concepts": "Concepts",
    "reference": "Reference",
    "help": "Help",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/stable", None),
}


KINDS = {"class": "class", "exception": "exc", "function": "func", "data": "type"}


def public_api() -> dict[str, object]:
    """Map every public name in modsmith to its object."""
    names: dict[str, object] = {}
    for module_name in modsmith.__all__:
        module = getattr(modsmith, module_name)
        if inspect.ismodule(module):
            names[module_name] = module
            for name in getattr(module, "__all__", ()):
                names[name] = getattr(module, name)
    return names


class ModsmithLexer(PythonLexer):
    """Python, with modsmith's API and method calls picked out.

    The standard lexer treats every name the same, so a call like
    `ms.platforms.Modrinth(...)` would have no colour at all.
    """

    api = public_api()

    def kind_of(self, value: str, previous: str) -> object | None:
        """Return the token type of a modsmith name, if it is one."""
        target = self.api.get(value)
        # A variable can share a module's name, so only `ms.launcher` counts.
        if value in ("ms", "modsmith") or (
            inspect.ismodule(target) and previous == "."
        ):
            return Name.Namespace
        if inspect.isclass(target):
            is_error = issubclass(target, Exception)
            return Name.Exception if is_error else Name.Class
        return None

    def get_tokens_unprocessed(self, text, stack=("root",)):
        """Refine the plain names that the standard lexer produces."""
        tokens = list(super().get_tokens_unprocessed(text, stack))
        depth = 0
        for index, (position, token, value) in enumerate(tokens):
            if value in ("(", "[", "{"):
                depth += 1
            elif value in (")", "]", "}"):
                depth -= 1
            if token is Name:
                previous = tokens[index - 1][2] if index else ""
                following = next(
                    (item[2] for item in tokens[index + 1 :] if item[2].strip()), ""
                )
                kind = self.kind_of(value, previous)
                if kind:
                    token = kind
                elif following == "(":
                    token = Name.Function
                elif following == "=" and depth > 0:
                    token = Name.Variable
                elif previous == ".":
                    token = Name.Attribute
            yield position, token, value


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


def page_name(name: str) -> str:
    """Turn `CancelToken` or `list_versions` into a name for a URL."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name).replace("_", "-").lower()


# Reference pages by the name of the object they describe, and the reverse.
OBJECT_PAGES = {
    f"modsmith.{module}.{name}": f"reference/{module}/{page_name(name)}"
    for module in modsmith.__all__
    if inspect.ismodule(getattr(modsmith, module))
    for name in getattr(getattr(modsmith, module), "__all__", ())
}
PAGE_OBJECTS = {page: name for name, page in OBJECT_PAGES.items()}
autosummary_filename_map = {
    name: page.rsplit("/", 1)[-1] for name, page in OBJECT_PAGES.items()
}


def add_object_kinds(app: Sphinx, pagename: str, context: dict) -> None:
    """Mark links to reference pages, and each page's title, with the object's kind."""
    objects = app.env.get_domain("py").objects  # type: ignore[attr-defined]

    def kind_of(page: str) -> str | None:
        entry = objects.get(PAGE_OBJECTS.get(page, ""))
        return KINDS.get(entry.objtype) if entry else None

    base = "/" if pagename == "index" else f"/{pagename.removesuffix('/index')}/"

    def mark(match: re.Match[str]) -> str:
        page = urljoin(base, match[2]).split("#")[0].strip("/")
        kind = kind_of(page)
        return f'{match[1]} data-kind="{kind}">' if kind else match[0]

    link = r'(<a [^>]*href="([^"]+)"[^>]*)>'
    context["body"] = re.sub(link, mark, context.get("body", ""))
    context["section_nav"] = re.sub(link, mark, context["section_nav"])
    kind = kind_of(pagename)
    if kind:
        context["body"] = context["body"].replace(
            "<h1>", f'<h1><span class="kind" data-kind="{kind}">{kind}</span>', 1
        )


def add_section_navigation(app, pagename, templatename, context, doctree) -> None:
    """Give each page the sidebar of its own section."""
    section = pagename.split("/")[0]
    context["section"] = section
    context["section_title"] = SECTIONS.get(section, "")
    context["section_nav"] = ""
    if section in SECTIONS and "toctree" in context:
        tree = context["toctree"](
            maxdepth=3, collapse=True, includehidden=True, titles_only=True
        )
        for part in re.split(r'(?=<p class="caption")', tree):
            if f">{SECTIONS[section]}<" in part:
                context["section_nav"] = part
    add_object_kinds(app, pagename, context)


def show_default_factories(
    app: Sphinx, what, name, obj, options, signature, return_annotation
) -> tuple[str, str | None] | None:
    """Replace `<factory>`, which is not valid Python and breaks signature parsing."""
    if signature is None or "<factory>" not in signature:
        return None
    if dataclasses.is_dataclass(obj):
        fields = [field.default_factory for field in dataclasses.fields(obj)]
    else:
        fields = [field.default_factory for field in obj.model_fields.values()]
    for factory in fields:
        if callable(factory):
            signature = signature.replace("<factory>", repr(factory()), 1)
    return signature, return_annotation


def publish_not_found_page(app: Sphinx, exception: Exception | None) -> None:
    """Copy the 404 page to the site root, where GitHub Pages looks for it."""
    page = Path(app.outdir, "404", "index.html")
    if exception is None and page.is_file():
        text = page.read_text(encoding="utf-8").replace('="../', '="')
        Path(app.outdir, "404.html").write_text(text, encoding="utf-8")


def setup(app: Sphinx) -> None:
    """Register the build hooks."""
    app.add_lexer("python", ModsmithLexer)
    app.connect("missing-reference", resolve_short_name)
    app.connect("html-page-context", add_section_navigation)
    app.connect("build-finished", publish_not_found_page)
    app.connect("autodoc-process-signature", show_default_factories)
