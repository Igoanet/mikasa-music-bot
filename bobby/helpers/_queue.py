# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import os
from collections import defaultdict, deque
from typing import Union

from ._dataclass import Media, Track

MediaItem = Union[Media, Track]


class Queue:
    def __init__(self):
        self.queues: dict[int, deque[MediaItem]] = defaultdict(deque)

    def add(self, chat_id: int, item: MediaItem) -> int:
        """Add an item to the queue and return its position (1-based)."""
        self.queues[chat_id].append(item)
        return len(self.queues[chat_id]) - 1

    def check_item(self, chat_id: int, item_id: str) -> tuple[int, MediaItem | None]:
        """Check if an item with the given ID exists in the queue."""
        pos, track = next(
            (
                (i, track)
                for i, track in enumerate(list(self.queues[chat_id]))
                if track.id == item_id
            ),
            (-1, None),
        )
        return pos, track

    def force_add(
        self, chat_id: int, item: MediaItem, remove: int | bool = False
    ) -> None:
        """Replace the currently playing item with a new one."""
        old = self.get_current(chat_id)
        self.remove_current(chat_id)
        self.queues[chat_id].appendleft(item)
        # the replaced track will never play again — free its sources (after the
        # replacement is in place: forcing the same song again shares its file)
        if old is not None and old is not item:
            self.purge_item(old)
        if remove:
            self.queues[chat_id].rotate(-remove)
            self.queues[chat_id].popleft()
            self.queues[chat_id].rotate(remove)

    def get_current(self, chat_id: int) -> MediaItem | None:
        """Return the currently playing item (first in queue), if any."""
        return self.queues[chat_id][0] if self.queues[chat_id] else None

    def get_next(self, chat_id: int, check: bool = False) -> MediaItem | None:
        """Remove current item and return the next one, or None if empty."""
        if not self.queues[chat_id]:
            return None
        if check:
            return self.queues[chat_id][1] if len(self.queues[chat_id]) > 1 else None

        self.queues[chat_id].popleft()
        return self.queues[chat_id][0] if self.queues[chat_id] else None

    def get_queue(self, chat_id: int) -> list[MediaItem]:
        """Return the full queue including the currently playing item."""
        return list(self.queues[chat_id])

    def remove_current(self, chat_id: int) -> None:
        """Remove the currently playing item only (if exists)."""
        if self.queues[chat_id]:
            self.queues[chat_id].popleft()

    def drop_item(self, chat_id: int, item: MediaItem) -> bool:
        """Remove this exact item (identity, not id) and free its sources.

        Used when a queued track must be taken back out — an autoplay pick
        that lost its chat to a real /play or /stop while its source was
        still being resolved. Identity matters: the same song may legitimately
        sit in the queue twice."""
        items = self.queues[chat_id]
        for i, queued in enumerate(items):
            if queued is item:
                del items[i]
                self.purge_item(item)
                return True
        return False

    def clear(self, chat_id: int) -> None:
        """Clear the entire queue."""
        self.queues[chat_id].clear()

    def referenced_paths(self) -> set[str]:
        """Every path some queue still needs: the playing/queued files plus the
        untempoed originals /speed keeps behind its tempo variants."""
        paths: set[str] = set()
        for items in self.queues.values():
            for item in items:
                for attr in ("file_path", "source_path"):
                    p = getattr(item, attr, None)
                    if p:
                        paths.add(str(p))
        return paths

    def purge_file(self, path: str | None) -> None:
        """Release a playback source once NO queue references it.

        Playback files are dead weight after a track finishes or is removed
        (they used to accumulate in downloads/ forever). The queues act as
        the refcount: the same video can be queued twice or playing in
        another chat, so only delete when truly unreferenced. Unlinking a
        file mid-stream is safe on Linux — the player holds an open fd.
        Spool URLs (remote audio buffered in RAM) are released the same way,
        so a finished song does not sit in memory for hours."""
        if not path:
            return
        path = str(path)
        if path in self.referenced_paths():
            return
        if path.startswith("http"):
            from bobby.core.spool import spool  # lazy: spool imports the logger package
            spool.forget(path)
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def purge_item(self, item: MediaItem | None) -> None:
        """purge_file for both sources an item may hold."""
        if item is None:
            return
        for attr in ("file_path", "source_path"):
            self.purge_file(getattr(item, attr, None))
