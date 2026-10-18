# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from dataclasses import dataclass


@dataclass
class Media:
    id: str
    duration: str = "00:00"
    duration_sec: int = 0
    file_path: str = None
    message_id: int = 0
    title: str = None
    url: str = None
    time: int = 0
    user: str = None
    video: bool = False
    # /speed: the untempoed original and its length once file_path points at
    # a tempo variant — every speed change is cut from the ORIGINAL, never
    # from the previous variant (speeds used to compound: 1.2 then 1.0 stayed
    # at 1.2x, each pass adding a generation of re-encode artefacts)
    source_path: str = None
    source_duration_sec: int = 0
    speed: float = 1.0


@dataclass
class Track:
    id: str
    channel_name: str = None
    duration: str = "00:00"
    duration_sec: int = 0
    title: str = None
    url: str = None
    file_path: str = None
    message_id: int = 0
    time: int = 0
    thumbnail: str = None
    user: str = None
    view_count: str = None
    video: bool = False
    # YouTube id the suggestion card relates from once this track has
    # ended — fixed at /play time because play_source may swap `id` to a
    # catalogue mirror; None for playlists, live feeds and Telegram files
    seed: str = None
    # /speed bookkeeping — see Media
    source_path: str = None
    source_duration_sec: int = 0
    speed: float = 1.0
