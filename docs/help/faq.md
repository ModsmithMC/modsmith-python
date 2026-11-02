# FAQ

## Is Modsmith a launcher?

No. It is a Python library for building tools. It prepares the game files, and the official launcher starts the game.

## Does it sign in to Microsoft accounts?

No. It never handles accounts. The official launcher does that.

## Does it need a copy of Minecraft?

It downloads game files from Mojang, as the launcher does. Players need to own the game to play it.

## Do I need Java installed?

No. Modsmith uses the official launcher's runtimes, or downloads one from Mojang. It only needs Java to install Forge and NeoForge.

## Do I need a CurseForge API key?

Only to use CurseForge. Reading a CurseForge `.zip` works without one, but downloading its files needs a key. Modrinth needs no key.

## Can I ship an API key inside my app?

Anyone can extract a key from a distributed app, so check CurseForge's terms and choose carefully. Tools that run on your own server can keep the key private.

## Why can't Modsmith download every CurseForge mod?

Some authors do not allow third-party downloads. See [Install CurseForge packs](../guides/curseforge.md).

## Can I install into `.minecraft` directly?

Use a separate instance folder. A sync manages every file it installs, and it would mix a pack's files with your other games.

## Can two packs share one game directory?

Yes. The game directory holds versions and libraries, which packs share. Each pack has its own instance.

## Is it safe to call from several threads?

A `Session` can be shared between threads. Avoid running two installs that write to the same folder at once, including the same cache directory, because they can collide on the same file.

## Does it work with servers?

`Instance.sync` accepts `side="server"`, which installs a server's files. Installing a loader for a server is not supported yet.

## Does it work with Bedrock Edition?

No. Modsmith only works with Java Edition.

## Is the API stable?

Not yet. Modsmith is in alpha, so the API may change between releases. [Changelog](changelog.md) lists what changed.
