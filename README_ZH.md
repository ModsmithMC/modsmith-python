# Modsmith

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Read in English](https://img.shields.io/badge/README-English-red?style=flat-square&logo=github)](README.md)

用于处理 Minecraft 整合包、模组加载器和游戏实例的 Python 工具库。

Modsmith 是一个库，不是启动器。它提供可自由组合的模块：搜索 Modrinth 和 CurseForge、读取整合包、安装模组加载器、管理游戏目录、操作官方启动器配置。它不负责账号登录，也不负责启动游戏。

## 示例

```python
import modsmith as ms

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    project = modrinth.get_project("fabulously-optimized")
    release = modrinth.list_releases(project, game_version="1.21.1")[0]
    pack = ms.packs.load(modrinth.fetch(release, ".cache"))

game = ms.minecraft.GameDir.default()
version_id = pack.loader.install(game)

instance = ms.instances.Instance.open("instances/fabulously-optimized")
print(instance.diff(pack))
instance.sync(pack)

ms.launcher.Launcher(game).add_profile(pack.name, version_id, instance.path)
```

每个模块也可以单独使用：

```python
pack = ms.packs.load("pack.mrpack")                       # 不需要网络和 API 密钥
ms.loaders.NeoForge("21.1.233", "1.21.1").install(game)   # 只安装加载器
```

## 模块

| 模块 | 提供的能力 |
| :--- | :--- |
| `modsmith.platforms` | `Modrinth`、`CurseForge` 和 `Platform` 基类 |
| `modsmith.packs` | `load()`、`Modpack`，支持 mrpack 和 CurseForge 格式 |
| `modsmith.loaders` | `Forge`、`NeoForge`、`Fabric`、`Quilt` 和 `Loader` 基类 |
| `modsmith.instances` | `Instance`，提供 `diff()` 和 `sync()` |
| `modsmith.minecraft` | `GameDir`、`Version`、原版版本下载 |
| `modsmith.java` | 查找官方启动器的运行时，或下载 Mojang 的运行时 |
| `modsmith.launcher` | 读取和修改启动器配置 |
| `modsmith.net` | `Resource`、`Session`，支持校验和断点续传的 `download()` |

耗时操作都接受 `progress=` 和 `cancel=` 参数。所有异常都继承自 `modsmith.errors.ModsmithError`。

## 开发

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```

访问真实服务器的测试需要主动开启：

```bash
uv run pytest tests/integration -o addopts="" -m network
```

## 许可证

[MIT](LICENSE)
