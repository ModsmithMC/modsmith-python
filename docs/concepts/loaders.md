# How loaders are installed

Mod loaders fall into two groups, and they install very differently.

## Fabric and Quilt

These publish a version file that lists the libraries they need. Modsmith downloads Minecraft and those libraries, then writes the version file. Nothing is changed in the game itself, so this is quick.

## Forge and NeoForge

These change the game's code, so they ship an installer with steps called processors. Each processor is a small Java program, and together they patch the game. They produce files that nothing else can provide, so these cannot simply be downloaded.

Modsmith does what the official installer does, without its window:

1. It downloads the installer, and checks it against the published hash when there is one.
2. It downloads the vanilla game and the libraries.
3. It runs each processor, and checks its output against the hash in the installer.
4. It registers the new version last, so a failed install leaves no broken version behind.

Finished steps are skipped if you run the install again.

## Which Java runs the processors

Processors are install tools, so they do not have to run on the Java that the game runs on. Modsmith tries runtimes in this order:

1. The Java you passed as `java=`.
2. The runtime the game version asks for, if it is installed.
3. Any other installed runtime, with `jre-legacy` last.
4. A download of the runtime the version asks for, then Java 21.
5. A download of `jre-legacy`, only if the version asks for it.

If a runtime fails, Modsmith moves on to the next one. `jre-legacy` comes last because newer runtimes work with every supported version, while Mojang's Windows build of `jre-legacy` produces different output for Forge 1.13.2, and it does not exist for Apple Silicon.

This only affects installation. The official launcher chooses which Java runs the game.

## Why versions need no network to check

The built-in loaders can work out their version id from their name and version, so `is_installed` only looks at local files.
