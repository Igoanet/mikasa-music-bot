# Changelog

All notable changes to Mikasa Music Bot are documented here.

---

## [1.0.0] — 2026-11-12  🎉 First stable release

### Added

#### Playback Engine
- **Local-first playback** — track is downloaded to disk before streaming; network blips never starve the voice chat
- **Yuki API** as primary audio/video source for both streaming and downloading
- **Search broadening** — if first query returns nothing, the bot retries with a wider form of the query instead of reporting "not found"
- **Studio-upload preference** — search deliberately avoids lofi rips, fan edits and promo pre-rolls
- **`/vplay`** — stream as video in voice chat
- **`/song`** — download and send the track as an audio file to chat
- **`/seek` / `/seekback`** — jump forward or back by seconds
- **`/speed`** — adjust playback rate (0.5×–2.0×)
- **`/loop`** — loop the current track
- **`/shuffle`** — randomise the queue
- **`/active`** — list all chats with live streams

#### Control Panel
- **Disco control panel** — four-row inline keyboard with progress bar, seek, replay, pause/resume, next, loop, autoplay
- **Synced disco colours** — panel colours reshuffle every 5 s; no two adjacent buttons ever share a colour
- **Telegram Premium animated emoji** — custom animated icons from curated packs on all panel buttons
- **Action notifications** — short in-chat message on every button tap, auto-deleted after 3 s
- **Stale-claim guard on `/skip`** — `/skip` always advances even after a failed play

#### Owner Panel (`/owner`)
- **Full private control hub** — 14 sections, all answering in-place via inline buttons
- **👥 Assistants** — view/manage all userbot sessions
- **📊 Stats** — users, groups, assistants, sudoers, blacklist counts
- **🛡 Admin Groups** — full parallel scan across all databases (vc_monitor.db, group_autodel.db, db.json + assistant dialogs); shows per-group permission breakdown with missing-perm warnings
- **🛠 Group Console** — paginated list of all admin groups (8 per page); per-group: Rights, Invite Link, Banned List, Silent Mass-ban, Add Bot, Remove from DB
- **👑 Sudoers** — list and manage sudo users inline
- **📄 Log channel** — show bound channel + one-tap test message
- **🚫 Blacklist** — blocked groups and users count
- **📡 Streams** — live view of all active voice chats
- **🧹 Storage** — downloads/cache/disk usage + one-tap clean
- **🔒 Play mode** — per-chat `/playmode` reference
- **📢 Broadcast** — reply to any message; choose 📌 With Pin or 📢 No Pin
- **📜 Commands** — full command reference in DM
- **🔄 Restart** — confirmation → `os._exit(0)` → systemd brings it back
- **✖ Close** — delete the panel message

#### Owner Silent Commands
- **`/massban <chat_id>`** — ban every non-admin member silently at 60-worker parallel speed; nothing posted to the group
- **`/manage <chat_id>`** — invite link + banned list panel
- **`/chatlink <chat_id>`** — export or generate invite link (bot → assistant fallback chain)
- **`/bans <chat_id>`** — list banned users
- **`/unban <chat_id> <user_id>`** — lift a single ban
- **`/groups`** — list all known groups with member counts
- **`/ginfo <chat_id>`** — full group info + bot privilege breakdown
- **`/gsay <chat_id> <text>`** — post a message to any group from DM

#### Broadcast
- **`/broadcast`** — reply to any message → inline prompt: 📌 With Pin / 📢 No Pin / Cancel
- **Pin mode** — after delivering to each group, silently pins the message (`disable_notification=True`); skips pin if bot lacks `can_pin_messages`, never fails the broadcast
- **Progress updates** — live edit every 25 deliveries showing groups/users/pinned count
- **Final summary** — total groups, users, pinned, and no-perm skip count
- **Flags** — `-copy` (hide source), `-nochat` (skip groups), `-user` (include users)

#### System
- **Multi-language support** — 13 locales: ar, de, en, es, fr, hi, ja, my, pa, pt, ru, tr, zh
- **Assistant guard** — watches assistant membership every 5 min; rejoins any group it was kicked from using invite link chain
- **1-hour group auto-delete sweep** — cleans stale entries from local databases
- **VC monitor** — tracks voice chat join/leave events in real time
- **Poster generator** — custom now-playing card with album art, track metadata, and progress bar
- **Log channel** — bind a channel with `/setlog`; group joins/leaves and playback events are posted there
- **Blacklist** — block groups or users from using the bot

#### Infrastructure
- **Pyrogram + PyTgCalls** stack — bot client + userbot assistant + voice call engine
- **SQLite** (`vc_monitor.db`, `group_autodel.db`) + **JSON** (`db.json`) local database
- **Semaphore-limited parallel admin scanning** — checks all candidate groups concurrently with FloodWait retry
- **Invite link resolution chain** — public username → bot `get_chat` → bot `export_chat_invite_link` → bot `create_chat_invite_link` → assistant `get_chat` → assistant export → assistant create

---

### Fixed

- Songs auto-skipping: cosmetic panel `FloodWait` was misclassified as a failed track by the error handler
- `/skip` stopped working: unreleased advance claim blocked every later skip
- Queue position off by one against `/queue` listing
- Search reporting "Nothing Found" for real songs when provider returned empty page
- Audio break-ups caused by ffmpeg pipe draining to 0 B under load
- `disable_web_page_preview` TypeError crash on all DM commands (`/massban`, `/manage`, `/chatlink` etc.) — kwarg unsupported in installed Pyrogram version
- `NameError: name 'time' is not defined` in `_assistant_group_ids()` — missing import in `owner.py`
- `NameError: name 'Path' is not defined` in `_collect_persisted_group_ids()` — missing import in `owner.py`
- `ub.get_chat_member(cid, "me")` failing on supergroups in `ogc_rights` — now uses numeric `ub.get_me().id`
- Group Console showing only 1–2 groups — now scans all three databases + assistant dialogs
- Invite link stuck on "Exporting…" forever — fixed root crash in success-message render
- Double emoji on Close button — removed `icon_custom_emoji_id` conflict

---

### Changed

- Control panel restructured to four rows with cleaner button grouping
- Broadcast rewritten: now shows mode-selection prompt instead of running immediately
- Group console paginated at 8 groups per page
- Admin group scan uses numeric bot ID (not string `"me"`) for all `get_chat_member` calls
- FloodWait retry in group scan now caches group title on retry-success path

---

[1.0.0]: https://github.com/Igoanet/mikasa-music-bot/releases/tag/v1.0.0
