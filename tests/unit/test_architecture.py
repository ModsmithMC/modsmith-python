"""Keep the package's layers and boundaries from drifting."""

import ast
import importlib
import inspect
from pathlib import Path

import modsmith

ROOT = Path(modsmith.__file__).parent
# A module may import only from modules in earlier layers.
LAYERS = [
    {"errors", "_version"},
    {"progress"},
    {"_fs", "_paths", "_locks"},
    {"net"},
    {"minecraft"},
    {"java", "launcher"},
    {"loaders"},
    {"packs", "metadata"},
    {"platforms"},
    {"instances"},
]
RANK = {name: index for index, layer in enumerate(LAYERS) for name in layer}
PACKAGES = {path.name for path in ROOT.iterdir() if (path / "__init__.py").is_file()}


def _type_checking_imports(tree: ast.Module) -> set[ast.AST]:
    """Return imports that only run for type checkers."""
    found: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", "") == "TYPE_CHECKING":
            found.update(
                item for item in ast.walk(node) if isinstance(item, ast.ImportFrom)
            )
    return found


def _imports() -> list[tuple[str, str, str, list[str], list[str]]]:
    """Return each import between modules.

    Each is the importing module, its file, the imported module, the import's
    path and the names it imports.
    """
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if relative == Path("__init__.py"):
            continue
        source = relative.parts[0].removesuffix(".py")
        package = list(relative.parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skipped = _type_checking_imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node in skipped:
                continue
            if node.level:
                base = package[: len(package) - node.level + 1]
                parts = base + (node.module.split(".") if node.module else [])
            elif node.module and node.module.split(".")[0] == "modsmith":
                parts = node.module.split(".")[1:]
            else:
                continue
            if parts and parts[0] != source:
                names = [alias.name for alias in node.names]
                found.append((source, relative.as_posix(), parts[0], parts, names))
    return found


def test_every_module_has_a_layer():
    modules = {path.stem for path in ROOT.glob("*.py")} | PACKAGES
    assert modules - {"__init__"} == set(RANK)


def test_modules_import_only_from_lower_layers():
    upward = [
        f"{where} imports {target}"
        for source, where, target, _, _ in _imports()
        if RANK[target] >= RANK[source]
    ]
    assert upward == []


def test_modules_do_not_import_private_names_from_each_other():
    private = [
        f"{where} imports {', '.join(names)} from {'.'.join(parts)}"
        for _, where, _, parts, names in _imports()
        if any(name.startswith("_") and name != "__version__" for name in names)
    ]
    assert private == []


def test_package_namespaces_hold_only_public_names():
    # Anything imported into a package's __init__ shows up in editors.
    leaked = []
    for package in sorted(PACKAGES):
        module = importlib.import_module(f"modsmith.{package}")
        public = set(module.__all__)
        for name, value in vars(module).items():
            if name.startswith("_") or name in public:
                continue
            if inspect.ismodule(value) and value.__name__.startswith(module.__name__):
                continue
            leaked.append(f"modsmith.{package}.{name}")
    assert leaked == []
