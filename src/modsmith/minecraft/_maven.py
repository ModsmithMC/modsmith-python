from dataclasses import dataclass


@dataclass(frozen=True)
class MavenCoord:
    group: str
    artifact: str
    version: str
    classifier: str | None = None
    extension: str = "jar"

    @classmethod
    def parse(cls, coord: str) -> "MavenCoord":
        body, _, extension = coord.partition("@")
        parts = body.split(":")
        if not 3 <= len(parts) <= 4 or "@" in extension:
            raise ValueError(f"Invalid maven coordinate: {coord}")
        return cls(
            group=parts[0],
            artifact=parts[1],
            version=parts[2],
            classifier=parts[3] if len(parts) == 4 else None,
            extension=extension or "jar",
        )

    @property
    def path(self) -> str:
        name = f"{self.artifact}-{self.version}"
        if self.classifier:
            name += f"-{self.classifier}"
        group = self.group.replace(".", "/")
        return f"{group}/{self.artifact}/{self.version}/{name}.{self.extension}"


def maven_path(coord: str) -> str:
    return MavenCoord.parse(coord).path
