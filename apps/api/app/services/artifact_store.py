"""Where uploaded bytes live, and the one path they may live under.

`09-security-spec.md` asks a reviewer two questions this module answers
structurally rather than by convention:

> *Can a filename influence a path?*

No. The caller never supplies a name. `new_key()` mints one from a UUID and the
extension already checked against the allow-list, so the only attacker-controlled
part of a stored object is its contents — which are never executed and never
interpreted here.

> *Are decompression bounds enforced before writing?*

`stage()` exists for that. An upload is streamed into a staging file that is
deleted unless it is explicitly committed, so validation runs against real bytes
while the artifact store still contains nothing. A file that fails a check was
never in the store to be cleaned up.

The `ArtifactStore` protocol is the seam for S3 and Azure Blob later
(02-architecture § Storage). Nothing above it may know it is talking to a
filesystem — which is also why `read` takes a key and not a path.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from contextlib import AbstractContextManager, contextmanager
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol, runtime_checkable

from dashboardbridge_contracts.enums import ErrorCategory

from app.core.config import settings
from app.core.errors import ApiException

#: `apps/api/app/services/artifact_store.py` → repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STORAGE_DIR = REPO_ROOT / ".data" / "artifacts"

#: Staging lives inside the root so a commit is a rename on the same volume —
#: atomic, and never a half-written object appearing under a final key.
STAGING_DIRNAME = "_staging"

_SUFFIX = re.compile(r"^\.[a-z0-9]{1,10}$")
_KEY = re.compile(r"^[a-f0-9]{2}/[a-f0-9]{32}\.[a-z0-9]{1,10}$")


class StorageKeyError(ApiException):
    """A key that does not name a location this store owns.

    A subclass of `ApiException` so a traversal attempt cannot become an
    unhandled 500 with a path in the body — the very thing being defended
    against would leak in the error.
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(
            ErrorCategory.SYSTEM_ERROR,
            "That file could not be located. It may have been removed.",
            detail=f"rejected storage key {key!r}: {reason}",
            status_code=404,
        )


@runtime_checkable
class ArtifactStore(Protocol):
    """Isolated storage under a generated name (§15)."""

    def new_key(self, *, suffix: str) -> str:
        """Mint a key. Never derived from anything the user supplied."""

    def stage(self) -> AbstractContextManager["StagedWrite"]:
        """A write that does not exist in the store until it is committed."""

    def read(self, key: str) -> bytes: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


class StagedWrite:
    """Bytes on their way in, not yet an artifact.

    Committing is the only way into the store, and it takes a key the store
    generated. Nothing else can name a destination.
    """

    def __init__(self, store: "LocalFilesystemStore", path: Path) -> None:
        self._store = store
        self._path = path
        self._handle: BinaryIO = path.open("wb")
        self._committed_key: str | None = None
        self.size_bytes = 0

    def write(self, chunk: bytes) -> None:
        self._handle.write(chunk)
        self.size_bytes += len(chunk)

    @property
    def path(self) -> Path:
        """The staging file, flushed.

        A property rather than an attribute so a reader cannot see a partially
        written file: the archive-bomb check reads this path while the upload
        is still in staging, and buffered bytes it could not see would make a
        valid zip look truncated — or, worse, a hostile one look valid.
        """
        if not self._handle.closed:
            self._handle.flush()
        return self._path

    def commit(self, key: str) -> str:
        destination = self._store.resolve(key)
        self._close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self._path, destination)
        self._committed_key = key
        return key

    # -- lifecycle ---------------------------------------------------------

    def _close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            self._handle.close()

    def discard(self) -> None:
        self._close()
        self._path.unlink(missing_ok=True)

    @property
    def committed(self) -> bool:
        return self._committed_key is not None


class LocalFilesystemStore:
    """The default store: a directory this process owns.

    Enough for local mode, the desktop shell, and a single-node deployment. S3
    and Azure Blob implement the same protocol when a deployment needs them.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._staging = self.root / STAGING_DIRNAME
        self._staging.mkdir(parents=True, exist_ok=True)

    # -- keys --------------------------------------------------------------

    def new_key(self, *, suffix: str) -> str:
        """`ab/<32 hex>.twbx` — a UUID and a checked extension, nothing else.

        The two-character prefix keeps a directory from growing to a million
        entries; it is not a namespace and carries no meaning.
        """
        lowered = suffix.lower()
        if not _SUFFIX.match(lowered):
            raise ApiException(
                ErrorCategory.SYSTEM_ERROR,
                "That file could not be stored.",
                detail=f"refusing to mint a key with suffix {suffix!r}",
                status_code=400,
            )
        token = uuid.uuid4().hex
        return f"{token[:2]}/{token}{lowered}"

    def resolve(self, key: str) -> Path:
        """The path a key names, or `StorageKeyError`.

        Three independent checks, because each catches what the others miss:
        the shape of the key, the parts it is made of, and — last — whether the
        resolved path is still inside the root after the operating system has
        had its say about symlinks and short names.
        """
        if not isinstance(key, str) or not key or key.strip() != key:
            raise StorageKeyError(key, "empty or padded key")
        if "\x00" in key:
            raise StorageKeyError(key, "NUL byte in key")
        if "\\" in key or key.startswith("/") or re.match(r"^[A-Za-z]:", key):
            raise StorageKeyError(key, "keys are relative, POSIX-separated names")
        parts = key.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise StorageKeyError(key, "path traversal")
        if not _KEY.match(key):
            raise StorageKeyError(key, "not a generated key")

        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageKeyError(key, "resolves outside the storage root")
        return candidate

    # -- writing -----------------------------------------------------------

    @contextmanager
    def stage(self) -> Iterator[StagedWrite]:
        handle = tempfile.NamedTemporaryFile(
            dir=self._staging, prefix="staged-", suffix=".part", delete=False
        )
        path = Path(handle.name)
        handle.close()
        staged = StagedWrite(self, path)
        try:
            yield staged
        finally:
            if staged.committed:
                staged._close()
            else:
                staged.discard()

    # -- reading -----------------------------------------------------------

    def read(self, key: str) -> bytes:
        path = self.resolve(key)
        if not path.is_file():
            raise StorageKeyError(key, "no object stored under this key")
        return path.read_bytes()

    def open(self, key: str) -> BinaryIO:
        path = self.resolve(key)
        if not path.is_file():
            raise StorageKeyError(key, "no object stored under this key")
        return path.open("rb")

    def exists(self, key: str) -> bool:
        try:
            return self.resolve(key).is_file()
        except StorageKeyError:
            return False

    def delete(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)

    def clear(self) -> None:  # pragma: no cover - operational helper
        shutil.rmtree(self.root, ignore_errors=True)
        self.__init__(self.root)


def storage_root() -> Path:
    """Configured location, or a directory beside the default database.

    Configured in `Settings` beside the other upload limits. The environment is
    still consulted directly so a test can point it somewhere throwaway without
    clearing the settings cache.
    """
    return Path(
        os.getenv("ARTIFACT_STORAGE_DIR")
        or settings().artifact_storage_dir
        or DEFAULT_STORAGE_DIR
    )


@lru_cache
def _default_store() -> LocalFilesystemStore:
    return LocalFilesystemStore(storage_root())


def get_artifact_store() -> ArtifactStore:
    """FastAPI dependency. Overridden in tests with a throwaway directory."""
    return _default_store()
