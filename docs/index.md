# Modsmith

```{raw} html
<div class="hero">
  <picture>
    <source media="(max-width: 560px)" srcset="_static/hero-library-small.svg">
    <img src="_static/hero-library.svg" alt="">
  </picture>
  <div class="hero-copy">
    <h2>Build your own modpack tools</h2>
    <p>A Python toolkit for Minecraft modpacks, mod loaders and game instances. It works alongside the official launcher.</p>
    <div class="actions">
      <a class="button primary" href="get-started/installation/">Get started</a>
      <a class="button" href="https://github.com/ModsmithMC/modsmith-python">View on GitHub</a>
    </div>
  </div>
</div>

<div class="band">
  <div class="band-inner">
    <div class="band-copy">
      <p class="eyebrow">Find</p>
      <h2>Two platforms, one API</h2>
      <p>Search Modrinth and CurseForge the same way, then read releases page by page. Finding the latest version takes a single request.</p>
    </div>
    <div>
```

```python
import modsmith as ms

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    project = modrinth.get_project("fabulously-optimized")
    release = next(modrinth.iter_releases(project))
    print(release.name)
```

```{raw} html
    </div>
  </div>
</div>

<div class="band alternate flip">
  <div class="band-inner">
    <div class="band-copy">
      <p class="eyebrow">Install</p>
      <h2>A modpack in a few lines</h2>
      <p>Read a pack, install its loader, sync the files and add a profile to the launcher. Every step also works on its own.</p>
    </div>
    <div>
```

```python
pack = ms.packs.load("fabulously-optimized.mrpack")

game = ms.minecraft.GameDir.default()
version_id = pack.loader.install(game)

instance = ms.instances.Instance("instances/my-pack")
instance.sync(pack)

launcher = ms.launcher.Launcher(game)
launcher.add_profile(pack.name, version_id, instance.path)
```

```{raw} html
    </div>
  </div>
</div>

<div class="band">
  <div class="band-inner">
    <div class="band-copy">
      <p class="eyebrow">Update</p>
      <h2>Updates that respect players</h2>
      <p>Preview every change before it happens. Files the player edited stay exactly as they are, unless you choose otherwise.</p>
    </div>
    <div class="changes">
      <p class="add"><b>added</b> mods/sodium.jar</p>
      <p class="update"><b>updated</b> mods/iris.jar</p>
      <p class="keep"><b>kept</b> config/options.toml <small>changed by the player</small></p>
      <p class="remove"><b>removed</b> mods/old-mod.jar</p>
    </div>
  </div>
</div>

<div class="band alternate center">
  <div class="band-inner">
    <p class="eyebrow">Load</p>
    <h2>Every major mod loader</h2>
    <p class="lede">One interface for all four, from Minecraft 1.13 to the latest release.</p>
    <div class="loaders">
      <div class="loader"><strong>Forge</strong><span>1.13.2 and later</span></div>
      <div class="loader"><strong>NeoForge</strong><span>1.20.1 and later</span></div>
      <div class="loader"><strong>Fabric</strong><span>1.14 and later</span></div>
      <div class="loader"><strong>Quilt</strong><span>1.14.4 and later</span></div>
    </div>
  </div>
</div>

<div class="band flip">
  <div class="band-inner">
    <div class="band-copy">
      <p class="eyebrow">Recover</p>
      <h2>Nothing breaks halfway</h2>
      <p>A failed update leaves the instance as it was, so players are never stuck with half a modpack.</p>
    </div>
    <ol class="steps">
      <li><strong>Check</strong> Everything the pack needs is found before any file changes.</li>
      <li><strong>Stage</strong> New files download and verify in a separate folder.</li>
      <li><strong>Commit</strong> Files move into place, and any failure puts them all back.</li>
    </ol>
  </div>
</div>

<div class="band alternate center">
  <div class="band-inner">
    <p class="eyebrow">Details</p>
    <h2>The hard parts are handled</h2>
    <p class="lede">The things every launcher tool has to get right.</p>
    <div class="features">
      <div class="feature"><img src="_static/pixel/cup.svg" alt=""><h3>The right Java</h3><p>Find a runtime in the official launcher, or download one from Mojang.</p></div>
      <div class="feature"><img src="_static/pixel/shield.svg" alt=""><h3>Verified downloads</h3><p>Every file is hash-checked, and interrupted downloads resume.</p></div>
      <div class="feature"><img src="_static/pixel/package.svg" alt=""><h3>Works offline</h3><p>Read modpacks with no network and no API key.</p></div>
      <div class="feature"><img src="_static/pixel/refresh.svg" alt=""><h3>Ready for a GUI</h3><p>Long-running calls report progress and can be cancelled.</p></div>
      <div class="feature"><img src="_static/pixel/search.svg" alt=""><h3>Blocked mods</h3><p>Find manually downloaded CurseForge files and verify them.</p></div>
      <div class="feature"><img src="_static/pixel/layers.svg" alt=""><h3>Easy to extend</h3><p>Add your own platforms, pack formats and loaders.</p></div>
    </div>
  </div>
</div>

<div class="band center closing">
  <div class="band-inner">
    <h2>Start building</h2>
    <p class="lede">Modsmith needs Python 3.12 or newer.</p>
    <div class="actions centered">
      <a class="button primary" href="get-started/installation/">Get started</a>
      <a class="button" href="https://modsmithmc.org/modsmith/">Just want to play? Use the command line</a>
    </div>
  </div>
</div>
```

```{toctree}
:hidden:
:caption: Get started

get-started/index
```

```{toctree}
:hidden:
:caption: Guides

guides/index
```

```{toctree}
:hidden:
:caption: Concepts

concepts/index
```

```{toctree}
:hidden:
:caption: Reference

reference/index
```

```{toctree}
:hidden:
:caption: Help

help/index
```
