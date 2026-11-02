# Installation

Modsmith needs Python 3.12 or newer. It is not on PyPI yet, so install it from GitHub:

```bash
pip install git+https://github.com/PaPa-jun/ModSmith
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/PaPa-jun/ModSmith
```

Check that it works:

```python
import modsmith as ms

print(ms.__version__)
```

You do not need to install Java yourself. Modsmith finds a runtime from the official launcher, or downloads one from Mojang when it has to.

## What Modsmith is for

Modsmith is a library for building your own Minecraft tools, such as a modpack installer, an update checker, a command-line tool or a desktop app.

It handles the work around the game: finding packs, installing mod loaders and keeping game files up to date. Players still start the game from the official launcher.

:::{note}
Modsmith does not sign in to accounts or start the game. If you need those, use it alongside a launcher.
:::

## Next steps

Follow the [quickstart](quickstart.md) to install your first modpack.
