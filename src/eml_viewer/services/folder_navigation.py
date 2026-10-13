"""Bounded reuse of the current folder's EML and MSG file list."""

from __future__ import annotations

import errno
import os
from pathlib import Path


class FolderNavigationService:
    """Cache one folder listing until it is explicitly invalidated.

    Call :meth:`invalidate` when the directory watcher reports a change and
    :meth:`refresh` for a user-requested refresh. Switching directories always
    scans the new directory. Returned paths are sorted case-insensitively.
    """

    _SUPPORTED_SUFFIXES = {".eml", ".msg"}

    def __init__(self) -> None:
        self._folder_key: str | None = None
        self._files: tuple[Path, ...] = ()
        self._valid = False
        self._folder_stamp: tuple[int, int, int] | None = None

    @staticmethod
    def _key(folder: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(folder)))

    def files(self, folder: str | os.PathLike[str]) -> tuple[Path, ...]:
        """Return a fresh-enough listing, checking directory identity and mtime."""
        key = self._key(folder)
        if self._valid and self._folder_key == key:
            try:
                current_stamp = self._stat_folder(folder)
            except OSError:
                self._clear()
                raise
            if current_stamp == self._folder_stamp:
                return self._files
        return self._scan(folder, key)

    @staticmethod
    def _stat_folder(folder: str | os.PathLike[str]) -> tuple[int, int, int]:
        stat_result = os.stat(folder)
        return (stat_result.st_dev, stat_result.st_ino, stat_result.st_mtime_ns)

    def _clear(self) -> None:
        self._valid = False
        self._files = ()
        self._folder_key = None
        self._folder_stamp = None

    def _scan(self, folder: str | os.PathLike[str], key: str) -> tuple[Path, ...]:
        # A pre/post stamp catches replacement or mutation during enumeration.
        # Retry a small bounded number of times if the folder keeps changing.
        self._clear()
        for _ in range(3):
            before = self._stat_folder(folder)
            paths: list[Path] = []
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if Path(entry.name).suffix.lower() not in self._SUPPORTED_SUFFIXES:
                            continue
                        if entry.is_file():
                            paths.append(Path(entry.path))
            except OSError:
                self._clear()
                raise
            after = self._stat_folder(folder)
            if before != after:
                continue
            paths.sort(key=lambda path: (path.name.lower(), path.name))
            self._folder_key = key
            self._files = tuple(paths)
            self._folder_stamp = after
            self._valid = True
            return self._files
        self._clear()
        raise OSError(errno.EAGAIN, "Folder changed during listing", os.fspath(folder))

    def refresh(self, folder: str | os.PathLike[str]) -> tuple[Path, ...]:
        """Force a fresh scan, even when *folder* is currently cached."""
        key = self._key(folder)
        return self._scan(folder, key)

    def invalidate(self, folder: str | os.PathLike[str] | None = None) -> None:
        """Invalidate the current cached folder, or the cache unconditionally."""
        if folder is None or self._folder_key == self._key(folder):
            self._clear()
