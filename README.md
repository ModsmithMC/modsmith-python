# CurseCraft: A CurseForge Resource Manager Designed for the Official Launcher

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Minecraft](https://img.shields.io/badge/minecraft-1.13+-green.svg)](https://www.minecraft.net)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Read in Chinese](https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-red?style=flat-square&logo=github)](README_ZH.md)

> **In a nutshell**: With CurseCraft, you can easily play mods, shaders, and large modpacks in the **Minecraft Official Launcher** without needing any third-party launchers.

## 📖 Project Introduction

With the booming development of the Minecraft community, large Modpacks have become increasingly popular, often containing hundreds of mods and complex resource configurations. Manually installing these resources is not only time-consuming and laborious but also prone to errors.

Currently, while excellent third-party launchers like HMCL and PCL2 offer one-click installation and management features, the **Minecraft Official Launcher** still lacks native support for modpacks. This makes it difficult for many players who wish to maintain an "authentic" experience or are restricted by their environment from using third-party launchers to manage game resources conveniently.

**CurseCraft** was born to solve this. It is not a game launcher but a resource installation and management tool focused on the **CurseForge ecosystem**. Its core philosophy is: **Zero Intrusion, Lightweight**.

- ❌ **No need** to replace your familiar launcher.
- ❌ **No need** to deal with complex Java version conflicts.
- ✅ **Directly** deploy resources to game directories recognizable by the official launcher.
- ✅ **Perfectly compatible** with the official launcher's version management and startup processes.

## ✨ Core Features

CurseCraft is dedicated to providing the purest resource installation experience:

- 🔍 **Comprehensive Search**: Directly search all resource types on the CurseForge platform, including Mods, Shaders, Data Packs, and large Modpacks.
- 📥 **Smart Deployment**: Automatically downloads and installs resources to the specified game directory, ensuring the file structure strictly complies with official launcher specifications.
- ⚙️ **One-Click Loader Configuration**: Built-in mod loader installation functionality, currently perfectly supporting:
  - **Forge**: `Minecraft 1.13` and later versions.
  - **NeoForge**: All supported game versions.
  - **Fabric**: All supported game versions.
  - *(Note: Given the scarcity of Quilt-exclusive resources, support for it is currently under evaluation)*
- 🛡️ **Safe and Clean**: Does not modify core launcher files or inject extra code. It acts solely as a resource porter, maximizing the stability of the game environment.

## 🚀 Quick Start

> ⚠️ **Note**: This project is currently in the **Beta development stage**. Core functions are implemented, but a unified Graphical User Interface (GUI) or Command Line Interface (CLI) has not been officially released yet.

### Current Status
The current version is primarily intended for testing by developers or advanced users. Upon the release of the official version, we will provide:

- A detailed installation wizard
- A concise and easy-to-use Command Line Interface (CLI)
- An intuitive Graphical User Interface (GUI) (Planned)

Please keep a close eye on the **Releases** page of this repository for notifications about the latest official versions.

### Expected Workflow (Official Release)

1. Run CurseCraft.
2. Search for the desired modpack or mod name.
3. Select the target Minecraft version and installation path (defaulting to the official launcher directory).
4. Execute the "Install" command (or click the button) and wait for completion.
5. Open the Minecraft Official Launcher and directly select the newly installed configuration from the version list to start playing.

## 🤔 Why Choose CurseCraft?

| Feature | Third-Party Launchers (HMCL/PCL2) | **CurseCraft + Official Launcher** |
| :--- | :---: | :---: |
| **Feature Richness** | ⭐⭐⭐⭐⭐ (Very High) | ⭐⭐ (Focused on Installation) |
| **Launcher Dependency** | Must use a specific launcher | **No replacement needed, retains official experience** |
| **Java Environment Management** | Automatic management (sometimes overly complex) | **Handled by the official launcher, more stable** |
| **Account Verification** | Requires configuring offline/online modes | **Native support for Microsoft account verification** |
| **Target Audience** | Geeks, Multi-version Managers | **Legitimate Players, Minimalists** |

## 🔮 Future Plans (Roadmap)

- [ ] Release the first Public Beta and GUI interface.
- [ ] Enables resumable downloads and enhanced stability, accelerating large file installations.
- [ ] Add support for the Modrinth platform to broaden resource sources.
- [ ] Provide configuration file export/import functions for easy migration and backup.
- [ ] Evaluate and add support for the Quilt loader.

## 🙏 Acknowledgments

This project would not be possible without the support of the following open-source communities and platforms:

- **[Minecraft](https://www.minecraft.net)** - For providing simply the best game in the world;
- **[CurseForge](https://www.curseforge.com/)** - For providing rich resource indexing and download APIs;
- **[Minecraft Forge](https://minecraftforge.net/)** - The classic mod loading framework;
- **[NeoForge](https://neoforged.net/)** - The modern branch of Forge;
- **[FabricMC](https://fabricmc.net/)** - The lightweight mod loading framework;
- All developers and players who contribute content to the Minecraft community.

## 📄 License

This project is open-sourced under the [MIT License](LICENSE).