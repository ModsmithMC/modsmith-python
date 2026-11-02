from dataclasses import dataclass


class CurseCraftError(Exception):
    pass


class ConfigError(CurseCraftError):
    pass


class HttpError(CurseCraftError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DownloadError(CurseCraftError):
    def __init__(self, message: str, failures: list[str] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []


class HashMismatchError(DownloadError):
    pass


class UnsupportedError(CurseCraftError):
    pass


class SourceError(CurseCraftError):
    pass


class LoaderInstallError(CurseCraftError):
    pass


class ProcessorError(LoaderInstallError):
    pass


class JavaNotFoundError(CurseCraftError):
    pass


class LauncherError(CurseCraftError):
    pass


class LauncherRunningError(LauncherError):
    pass


class InstanceError(CurseCraftError):
    pass


@dataclass(frozen=True)
class ManualDownload:
    file_name: str
    url: str
    dest: str


class ManualDownloadRequired(CurseCraftError):
    def __init__(self, items: list[ManualDownload]) -> None:
        names = ", ".join(item.file_name for item in items)
        super().__init__(f"{len(items)} file(s) must be downloaded manually: {names}")
        self.items = items
