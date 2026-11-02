# CurseCraft: 专为官方启动器打造的 CurseForge 资源管理器

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Minecraft](https://img.shields.io/badge/minecraft-1.13+-green.svg)](https://www.minecraft.net)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Read in Chinese](https://img.shields.io/badge/README-English-red?style=flat-square&logo=github)](README.md)

> **一句话概括**：使用 CurseCraft，无需第三方启动器，即可在 Minecraft **官方启动器**中轻松游玩模组、光影及大型整合包。

## 📖 项目简介

随着 Minecraft 社区的蓬勃发展，大型 Mod 整合包（Modpacks）日益普及，其中往往包含上百个模组及复杂的资源配置。手动安装这些资源不仅耗时费力，还极易出错。

目前，虽然 HMCL、PCL2 等优秀的第三方启动器提供了一键安装和管理功能，但 **Minecraft 官方启动器** 却始终缺乏对整合包的原生支持。这导致许多希望保持“原汁原味”体验、或受限于环境无法使用第三方启动器的玩家，难以便捷地管理游戏资源。

**CurseCraft** 应运而生。它不是一个游戏启动器，而是一个专注于 **CurseForge 生态的资源安装与管理工具**。它的核心理念是：**零侵入、轻量化**。

- ❌ **不需要**替换你习惯的启动器；
- ❌ **不需要**处理复杂的 Java 版本冲突；
- ✅ **直接**将资源部署到官方启动器可识别的游戏目录；
- ✅ **完美兼容**官方启动器的版本管理与启动流程。

## ✨ 核心特性

CurseCraft 致力于提供最纯净的资源安装体验：

- 🔍 **全能检索**：直接搜索 CurseForge 平台上的所有资源类型，包括模组 (Mods)、光影 (Shaders)、数据包 (Data Packs) 以及大型整合包 (Modpacks)。
- 📥 **智能部署**：自动下载并将资源安装至指定的游戏目录，确保文件结构严格符合官方启动器规范。
- ⚙️ **加载器一键配置**：内置模组加载器安装功能，目前已完美支持：
  - **Forge**：`Minecraft 1.13` 及之后的版本；
  - **NeoForge**：支持的所有游戏版本；
  - **Fabric**：支持的所有游戏版本；
  - *(注：鉴于 Quilt 独占资源较少，对其的支持正在评估中)*
- 🛡️ **安全纯净**：不修改启动器核心文件，不注入额外代码，仅作为资源搬运工，最大程度保障游戏环境的稳定性。

## 🚀 快速开始

> ⚠️ **注意**：本项目目前处于 **Beta 开发阶段**。核心功能已实现，但统一的图形用户界面 (GUI) 或命令行接口 (CLI) 尚未正式发布。

### 当前状态
目前的版本主要面向开发者或高级用户进行测试。正式版本发布后，我们将提供：

- 详细的安装向导
- 简洁易用的命令行接口 (CLI)
- 直观的图形化操作界面 (GUI)（计划中）

请密切关注本仓库的 **Releases** 页面以获取最新正式版通知。

### 预期工作流 (正式版)

1. 运行 CurseCraft。
2. 搜索想要的整合包或模组名称。
3. 选择目标 Minecraft 版本及安装路径（默认为官方启动器目录）。
4. 执行“安装”指令（或点击按钮），等待完成。
5. 打开 Minecraft 官方启动器，直接在版本列表中选择刚安装的配置开始游戏。

## 🤔 为什么选择 CurseCraft？

| 特性 | 第三方启动器 (HMCL/PCL2) | **CurseCraft + 官方启动器** |
| :--- | :---: | :---: |
| **功能丰富度** | ⭐⭐⭐⭐⭐ (极高) | ⭐⭐ (专注安装) |
| **启动器依赖** | 必须使用特定启动器 | **无需更换，保留官方体验** |
| **Java 环境管理** | 自动管理 (有时过于复杂) | **由官方启动器接管，更稳定** |
| **账号验证** | 需配置离线/在线模式 | **原生支持微软账号验证** |
| **适用人群** | 极客、多版本管理者 | **正版玩家、简洁主义者** |

## 🔮 未来计划 (Roadmap)

- [ ] 发布首个公开测试版 (Public Beta) 及 GUI 界面；
- [ ] 支持断点续传及更稳健的下载机制，显著提升大文件安装效率；
- [ ] 增加对 Modrinth 平台的支持，拓宽资源来源；
- [ ] 提供配置文件导出/导入功能，方便迁移与备份；
- [ ] 评估并添加对 Quilt 加载器的支持；

## 🙏 鸣谢

本项目离不开以下开源社区与平台的支持：

- **[Minecraft](https://www.minecraft.net)** - 提供了简直是世界上最好的游戏；
- **[CurseForge](https://www.curseforge.com/)** - 提供丰富的资源索引与下载 API；
- **[Minecraft Forge](https://minecraftforge.net/)** - 经典的模组加载框架；
- **[NeoForge](https://neoforged.net/)** - Forge 的现代分支；
- **[FabricMC](https://fabricmc.net/)** - 轻量级模组加载框架；
- 所有为 Minecraft 社区贡献内容的开发者与玩家。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。