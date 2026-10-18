# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import json
import os
import tempfile

from pyrogram import filters, types

from bobby import anon, app, db, lang, queue, yt
from bobby.helpers import can_manage_vc, is_live_group_admin
from bobby.helpers._dataclass import Track

_EXPORTABLE = (
    "id",
    "title",
    "url",
    "duration",
    "duration_sec",
    "user",
    "video",
    "thumbnail",
    "channel_name",
)


@app.on_message(filters.command(["export", "ep"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _export(_, m: types.Message):
    items = [t for t in queue.get_queue(m.chat.id) if isinstance(t, Track)]
    if not items:
        return await m.reply_text(
            m.lang.get("export_empty", "❌ The queue is empty — nothing to export.")
        )

    data = {
        "format": "bobbyxmusic-queue",
        "version": 1,
        "tracks": [
            {key: getattr(t, key) for key in _EXPORTABLE} for t in items
        ],
    }

    path = os.path.join(tempfile.gettempdir(), f"queue_{m.chat.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    try:
        await m.reply_document(
            document=path,
            caption=m.lang.get(
                "export_done",
                "📤 Exported {0} track(s). Reply to this file with /import in any group to restore the queue.",
            ).format(len(items)),
        )
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.on_message(filters.command(["import", "ip"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _import(_, m: types.Message):
    doc = m.reply_to_message.document if m.reply_to_message else None
    if not doc or not (doc.file_name or "").endswith(".json"):
        return await m.reply_text(
            m.lang.get("import_usage", "❓ Reply to a queue export file with /import.")
        )

    # Importing can immediately start the first queued item, so it follows
    # the same live-admin rule as /play while this chat is in strict mode.
    if await db.get_play_mode(m.chat.id) and not await is_live_group_admin(
        m.chat.id, m
    ):
        return await m.reply_text(m.lang["play_admin"])

    sent = await m.reply_text(m.lang.get("processing", "Processing..."))
    path = await m.reply_to_message.download()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tracks") if isinstance(data, dict) else data
        tracks = [
            Track(
                id=str(t["id"]),
                title=t.get("title") or "Unknown",
                url=t.get("url"),
                duration=t.get("duration") or "00:00",
                duration_sec=int(t.get("duration_sec") or 0),
                user=m.from_user.mention,
                video=bool(t.get("video")),
                thumbnail=t.get("thumbnail"),
                channel_name=t.get("channel_name"),
            )
            for t in raw
            if isinstance(t, dict) and t.get("id") and t.get("url")
        ]
    except Exception:
        tracks = []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not tracks:
        return await sent.edit_text(
            m.lang.get("import_bad", "❌ That file isn't a valid queue export.")
        )

    chat_id = m.chat.id
    for track in tracks:
        queue.add(chat_id, track)

    # nothing playing -> start the imported queue from the top
    if not await db.get_call(chat_id):
        media = queue.get_current(chat_id)
        media.message_id = sent.id
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        if not media.file_path:
            await sent.edit_text(
                m.lang["error_no_file"].format("https://t.me/toolatetobloom")
            )
            return await anon.play_next(chat_id)
        return await anon.play_media(chat_id, sent, media)

    await sent.edit_text(
        m.lang.get("import_done", "📥 Imported {0} track(s) into the queue.").format(
            len(tracks)
        )
    )
