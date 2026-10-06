"""Landing-zone sink: the generator writes events as files that Spark Structured Streaming ingests."""
import os
import uuid
from collections import defaultdict
from pathlib import Path


class FileSink:
    """Writes newline-delimited JSON files per stream, the shape Spark's file source streams.

    Files are written under a dot-prefixed temporary name and renamed when complete, so a
    streaming reader never picks up a half-written file.
    """

    def __init__(self, landing_dir: str | Path, events_per_file: int = 2000):
        self.landing_dir = Path(landing_dir)
        self.events_per_file = events_per_file
        self._buffers: dict[str, list[str]] = defaultdict(list)

    def send(self, stream: str, key: str, value: str) -> None:
        buffer = self._buffers[stream]
        buffer.append(value.replace("\n", " "))
        if len(buffer) >= self.events_per_file:
            self._write(stream)

    def _write(self, stream: str) -> None:
        lines = self._buffers.pop(stream, [])
        if not lines:
            return
        directory = self.landing_dir / stream
        directory.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex}.json"
        temporary = directory / f".{name}.tmp"
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, directory / name)

    def flush(self) -> None:
        for stream in list(self._buffers):
            self._write(stream)

    def close(self) -> None:
        self.flush()
