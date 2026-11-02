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

## Commits

Keep the change focused, write the subject in the imperative mood, and add a
line to `CHANGELOG.md` under `Unreleased` when users will notice the change.
