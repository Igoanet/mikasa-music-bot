# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""/clean (owner + sudo): throw away everything a song or a voice job could have
left behind — orphaned playback files, generated thumbnails, voice-feature scratch
and the songs still buffered in RAM — and show what the bot holds afterwards.

The automatic side (a janitor every 30 min plus the per-song release) lives in
bobby/core/housekeeping.py; this is the "clean it now" button on top of it."""

from pyrogram import filters, types

from bobby import app, lang
from bobby.core import housekeeping


def _mb(n: int | float) -> str:
    n = float(n) / 1048576
    return f"{n:.0f} MB" if n >= 10 else f"{n:.1f} MB"


def _gb(n: int | float) -> str:
    return f"{float(n) / 1073741824:.1f} GB"


@app.on_message(filters.command(["clean", "cleanup"]) & app.sudoers)
@lang.language()
async def _clean(_, m: types.Message):
    sent = await m.reply_text(m.lang.get("processing", "Processing..."))
    freed = await housekeeping.clean()
    u = await housekeeping.usage()

    lines = [
        m.lang.get("clean_done", "🧹 <b>Cleaned.</b>"),
        m.lang.get("clean_freed", "Removed {0} files ({1}) and released {2} of RAM.").format(
            freed["files"], _mb(freed["bytes"]), _mb(freed["spool_bytes"]),
        ),
        "",
        m.lang.get("clean_now", "<b>What the bot keeps now:</b>"),
        f"• {m.lang.get('clean_downloads', 'Playback files')}: {u['downloads'][0]} ({_mb(u['downloads'][1])})",
        f"• {m.lang.get('clean_cache', 'Thumbnails')}: {u['cache'][0]} ({_mb(u['cache'][1])})",
        f"• {m.lang.get('clean_spool', 'Songs buffered in RAM')}: {u['spool']['entries']} ({_mb(u['spool']['bytes'])})",
        f"• {m.lang.get('clean_scratch', 'Voice scratch files')}: {u['scratch'][0]} ({_mb(u['scratch'][1])})",
        f"• {m.lang.get('clean_log', 'Logs')}: {_mb(u['log'][1])}",
        f"• {m.lang.get('clean_voices', 'Saved voices')}: {u['voices'][0]} ({_mb(u['voices'][1])})",
        f"• {m.lang.get('clean_models', 'Voice engines (models, fixed)')}: {_gb(u['models'][1])}",
    ]
    if u["workers"]:
        lines.append(
            f"• {m.lang.get('clean_workers', 'Voice engine in memory')}: "
            + ", ".join(f"{name} {rss:.0f} MB" for name, rss in u["workers"])
        )
    lines.append("")
    lines.append(m.lang.get(
        "clean_auto",
        "<i>Automatic: a song's file is deleted when it can no longer play; thumbnails "
        "after 24 h; leftovers every 30 min.</i>",
    ))
    await sent.edit_text("\n".join(lines))
