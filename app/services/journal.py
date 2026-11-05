import fcntl
import json
import os
from pathlib import Path
from typing import Any


class JournalError(RuntimeError):
    pass


class JsonlJournal:
    """Append-only journal with OS-released advisory writer lock and corruption detection."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "events.jsonl"
        self.lock_path = directory / ".writer.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise JournalError("Journal already has a writer; another engine owns this journal") from exc
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def append(self, event: dict[str, Any]) -> None:
        if self._fd is None:
            raise JournalError("Journal append requires exclusive writer ownership")
        try:
            encoded = json.dumps(event, default=str, allow_nan=False)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except (OSError, TypeError, ValueError) as exc:
            raise JournalError(f"Journal write failed: {exc}") from exc

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        output = []
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    output.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise JournalError(f"Corrupt journal at line {line_number}") from exc
        return output
