# How sync works

`Instance.sync` makes a folder match a modpack. Its main promise is that a failed update does not leave a broken game. It keeps that promise with three steps.

## Check

Before it changes anything, `sync` works out what it needs. It reads the pack, compares it with the folder and looks for any files that have to come from the player.

If something is missing, it raises `UnresolvedEntriesError` here, and the instance is untouched.

## Stage

New files go into `.modsmith/staging` inside the instance, and are verified there. The game's files do not change during this step, however long the downloads take.

If a download fails or is cancelled, the staged files stay in place. The next sync reuses them and fetches only what is left.

## Commit

When every file is ready, Modsmith swaps them in:

1. It moves the files being replaced or removed into `.modsmith/backup`.
2. It moves the new files into place.
3. It deletes the backup and the staging folder, then records the sync.

This step only moves files on one disk, so it is quick. If a move fails, usually because a running game has locked a mod, Modsmith puts every file back and raises `InstanceError`.

If the computer loses power during this step, Modsmith cannot undo it straight away. The next sync finds the backup and restores it before it starts.

## How player changes are detected

Modsmith records a hash of every file it installs, in `.modsmith/instance.json`. On the next sync it sorts each file by comparing three things: the file on disk, the file in the pack and the recorded hash.

| On disk | Result |
| :--- | :--- |
| Missing | Added |
| Matches the pack | Unchanged |
| Matches the record, but not the pack | Updated, because the player did not edit it |
| Matches neither | A conflict, because the player edited it |

A file the pack no longer has is removed if it still matches the record. If the player edited it, it stays, and appears in `orphaned`.

Files Modsmith did not install are never touched.

## Why a sync with nothing to do is fast

Hashing every mod on each run would be slow, so Modsmith remembers hashes in `.modsmith/hashes.json`. A file whose size and modification time have not changed is not read again.

This has one limit. A file changed without changing its size or time looks unchanged. That does not happen in normal use, and files changed in the last few seconds are never cached.

## Space

An update briefly needs extra disk space, roughly the size of the files that changed.

## The `.modsmith` folder

| Path | Contents |
| :--- | :--- |
| `instance.json` | What the last sync installed |
| `hashes.json` | Remembered file hashes. It is safe to delete |
| `staging/` | New files waiting to be installed |
| `backup/` | Replaced files, during a commit |
