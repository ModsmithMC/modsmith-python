# Show progress and cancel

Installs can take minutes, so tools need to show what is happening. Long-running calls accept `progress` and `cancel`.

## Progress

`progress` is a function that receives a `modsmith.Progress`:

```python
import modsmith as ms


def show(event: ms.Progress) -> None:
    print(f"{event.task}: {event.current}/{event.total} {event.unit}")


pack = ms.packs.load("pack.mrpack")
instance = ms.instances.Instance("instances/my-pack")

instance.sync(pack, progress=show)
```

`task` names the current stage, and `unit` says what is counted. These are the values you will see:

| Task | Stage | Unit |
| :--- | :--- | :--- |
| `minecraft` | Downloading the game | `byte` or `file` |
| `libraries` | Downloading a loader's libraries | `byte` or `file` |
| `processors` | Patching the game for Forge or NeoForge | `step` |
| `java` | Downloading a Java runtime | `byte` or `file` |
| `files` | Downloading a pack's files | `byte` or `file` |
| `overrides` | Writing a pack's own files | `file` |
| `fetch` | Downloading a modpack | `byte` or `file` |

`total` is `None` if it is unknown. A download counts bytes when every file's size is known, and files otherwise. The number can fall if a corrupt file has to be downloaded again.

:::{warning}
Downloads call `progress` from worker threads, one call at a time. In a GUI, hand the update to your main thread rather than changing widgets directly.
:::

## Cancel

Create a `modsmith.CancelToken` and call `cancel` from another thread, such as your GUI's event handler:

```python
import threading

token = ms.CancelToken()
threading.Timer(0.01, token.cancel).start()

try:
    instance.sync(pack, cancel=token)
except ms.errors.Cancelled:
    print("Stopped")
```

The call raises `modsmith.errors.Cancelled` the next time it checks the token. Downloads keep their progress, so running the call again continues from there.

## In a desktop app

Run the work on a background thread, and connect these two arguments to your interface:

```python
def install(pack, instance, progress, token):
    try:
        instance.sync(pack, progress=progress, cancel=token)
    except ms.errors.Cancelled:
        return "cancelled"
    except ms.errors.ModsmithError as error:
        return str(error)
    return "done"
```
