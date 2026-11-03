# Manage Java

Most tools never need this page, because installing a loader finds Java for you. Use `modsmith.java` when you want to choose a runtime yourself or show it to the player.

Mojang publishes Java as named components, such as `java-runtime-delta`.

## Find what a version needs

```python
import modsmith as ms

game = ms.minecraft.GameDir.default()
ms.minecraft.install_version(game, "1.21.1")

component = ms.java.required_for(game.version("1.21.1"), game)
print(component)
```

## Find or download a runtime

`find` looks in the official launcher and in Modsmith's cache:

```python
runtime = ms.java.find(component, game=game)
```

`download` fetches a runtime into Modsmith's cache. It never changes the launcher's folder.

```python
if runtime is None:
    runtime = ms.java.download(component)

print(runtime.executable)
```

`find_all` lists every runtime that is installed:

```python
for runtime in ms.java.find_all(game=game):
    print(runtime.component, runtime.executable)
```

## Not every runtime exists everywhere

Mojang does not publish every component for every system. For example, `jre-legacy` has no build for Apple Silicon, so `download` raises `modsmith.errors.JavaError` there.
