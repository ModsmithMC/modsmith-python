"""Maven coordinates, used to locate library files."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MavenCoord:
    """A parsed coordinate such as ``group:artifact:version:classifier@extension``.

    Attributes:
        group: The group id.
        artifact: The artifact id.
        version: The version.
        classifier: The classifier, or None.
        extension: The file extension.
    """

    group: str
    artifact: str
    version: str
    classifier: str | None = None
    extension: str = "jar"

    @classmethod
    def parse(cls, coord: str) -> "MavenCoord":
        """Parse a coordinate.

        Args:
            coord: The coordinate. The classifier and extension are optional.

        Returns:
            The parsed coordinate.

        Raises:
            ValueError: The coordinate is malformed.
        """
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
        """The file's path inside a Maven repository."""
        name = f"{self.artifact}-{self.version}"
        if self.classifier:
            name += f"-{self.classifier}"
        group = self.group.replace(".", "/")
        return f"{group}/{self.artifact}/{self.version}/{name}.{self.extension}"


def maven_path(coord: str) -> str:
    """Convert a coordinate to its path inside a Maven repository.

    Args:
        coord: The coordinate.

    Returns:
        The relative path, with forward slashes.

    Raises:
        ValueError: The coordinate is malformed.

    Example:
        >>> maven_path("net.fabricmc:fabric-loader:0.16.10")
        'net/fabricmc/fabric-loader/0.16.10/fabric-loader-0.16.10.jar'
    """
    return MavenCoord.parse(coord).path
