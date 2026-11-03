# Handle errors

Every error derives from `modsmith.errors.ModsmithError`, so one `except` can catch them all:

```python
import modsmith as ms
from modsmith.errors import ModsmithError

try:
    pack = ms.packs.load("pack.mrpack")
    instance = ms.instances.Instance.open("instances/my-pack")
    instance.sync(pack)
except ModsmithError as error:
    print(f"Install failed: {error}")
```

Errors from your own mistakes, such as passing the wrong type, are ordinary Python errors.

## Which error to catch

| Error | Meaning |
| :--- | :--- |
| `Cancelled` | A `CancelToken` stopped the call |
| `LockedError` | Another process or thread is using the same files |
| `NetworkError` | A request failed. `status` holds the HTTP status, if there was one |
| `DownloadError` | A download failed. `failures` lists a reason for each file |
| `IntegrityError` | A file has the wrong size or hash |
| `UnsupportedError` | The version, loader or format is not supported |
| `PackError` | A modpack file is invalid |
| `PlatformError` | A platform could not provide what was requested |
| `LoaderError` | A loader could not be installed |
| `ProcessorError` | A Forge or NeoForge install step failed |
| `JavaError` | A Java runtime could not be found or installed |
| `LauncherError` | The launcher's files could not be used |
| `InstanceError` | An instance could not be read or changed |
| `UnresolvedEntriesError` | A pack still has files with no download |

`ProcessorError` is a kind of `LoaderError`, and `UnresolvedEntriesError` is a kind of `InstanceError`.

## Report failed downloads

A download keeps going when one file fails, then reports them all together:

```python
from modsmith.errors import DownloadError

try:
    instance.sync(pack)
except DownloadError as error:
    for failure in error.failures:
        print(failure)
```

## Tell a bad key from a bad connection

```python
from modsmith.errors import NetworkError

try:
    ms.platforms.Modrinth("my-tool/1.0").get_project("sodium")
except NetworkError as error:
    if error.status is None:
        print("No connection")
    else:
        print("The server answered", error.status)
```

## Retries

Modsmith already retries connection failures, timeouts, and HTTP 429 and 5xx responses, and waits as long as a server asks, up to one minute. A `modsmith.net.Session` lets you change this:

```python
session = ms.net.Session("my-tool/1.0", attempts=6, backoff=2.0)
modrinth = ms.platforms.Modrinth(session=session)
```

## Logs

Modsmith writes warnings to the `modsmith` logger, such as when a download moves to another mirror. It stays silent unless you turn logging on:

```python
import logging

logging.basicConfig(level=logging.INFO)
```
