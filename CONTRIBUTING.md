# Contributing

## Setup

You need [uv](https://docs.astral.sh/uv/) and a JDK, because the functional
tests compile and run a small processor jar.

```bash
uv sync
```

```bash
uv run pre-commit install
```

## Checks

Run these before you open a pull request:

```bash
uv run ruff format .
```

```bash
uv run ruff check .
```

```bash
uv run pyright
```

```bash
uv run pytest --cov
```

## Testing

| Layer | Contains | Runs |
| :--- | :--- | :--- |
| `tests/unit` | Pure logic and real local files | By default |
| `tests/functional` | A real local HTTP server and a real JVM; the internet is blocked | By default |
| `tests/live` | Real platforms and complete loader installs | On request |

Run the live tests with:

```bash
uv run pytest tests/live
```

CurseForge tests need `CURSEFORGE_API_KEY` and are skipped without it.

Tests do not use mocks. Do not use `unittest.mock`, patch internal functions or
fake a process or an HTTP client. Setting environment variables with
`monkeypatch` is allowed, because that configures the environment. If code is
hard to test this way, give it a parameter, such as a URL, instead.

Platform behaviour is tested only in `tests/live`, against the real services.

### Known gaps

- `replace_file` falls back to copying when a rename fails with `EXDEV`. The
  cross-filesystem test only runs when the working directory and the temp
  directory are on different drives. The MSIX behaviour that needed the
  fallback cannot be reproduced in a normal environment.
- `is_running()` is checked against the real process table, but no test starts
  the official launcher, and the Microsoft Store launcher's process name is
  unconfirmed.
- No test starts the game.

## Code layout

Each public module is a file or a package under `modsmith/`. Inside a package,
modules whose names start with `_` hold the implementation, and the package's
`__init__.py` lists the public names in `__all__`.

- A module imports only from modules in lower layers. The order is in
  `tests/unit/test_architecture.py`, which fails if an import goes the other
  way.
- Inside the library, a package may import another package's private
  modules, such as `..net._session`, but never names that start with `_`.
  Do not re-export internal names from a package's `__init__.py`, because
  editors would then offer them to users.
- Helpers shared by many packages live in private top-level modules, such as
  `_fs.py`.
- The full public API is listed in `tests/unit/test_public_api.py`. Change that
  list, the reference pages and the changelog together.

A convenience may sit on top of the core when it is built only from public
parts, serves a common task, returns existing types and leaves policy, such as
where files go, to the caller.

## Docstrings

Write Google-style docstrings, in English, for every module, class and function.
Ruff checks that they exist, so also check that they match what the code does.

- Describe behaviour. Type annotations already give the types.
- Add `Args`, `Returns` and `Raises` when a caller needs them.
- Use single backticks for modsmith objects, which become links in the
  documentation, and double backticks for parameters and literal values.
- Use a code comment only to explain why something is done.

## Documentation

The site is built with Sphinx and MyST, and the API reference comes from the
docstrings. Warnings and broken references fail the build:

```bash
uv run sphinx-build -W -n -b dirhtml docs docs/_build/html
```

Examples in docstrings run as tests:

```bash
uv run sphinx-build -W -b doctest docs docs/_build/doctest
```

## Continuous integration

| Workflow | Runs | Does |
| :--- | :--- | :--- |
| `ci.yml` | Pull requests and pushes to `main` and `develop` | Lint, type checks, tests on every Python version on Linux and one each on Windows and macOS, lowest dependencies, documentation, package build |
| `live.yml` | Every Monday, or by hand | Runs `tests/live` on every OS |
| `release.yml` | `v*` tags | Runs CI, publishes to PyPI and creates a GitHub release |

`live.yml` reads `CURSEFORGE_API_KEY` from the repository secrets.

## Releasing

New versions are developed on `develop`, and `main` holds released work.
Develop each feature on its own branch cut from `develop`, and merge it back
through a pull request.

1. Set `version` in `pyproject.toml` and move the `Unreleased` notes in
   `CHANGELOG.md` under the new version.
2. Merge `develop` into `main`.
3. Push a tag such as `v0.1.0`. The tag must match the project version, and
   the release notes come from that version's section of `CHANGELOG.md`.

## Commits

Keep the change focused, write the subject in the imperative mood, and add a
line to `CHANGELOG.md` under `Unreleased` when users will notice the change.
