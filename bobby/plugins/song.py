# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import os

from pyrogram import filters, types

from bobby import app, lang, yt


@app.on_message(filters.command(["song", "music", "audio"]) & ~app.bl_users)
@lang.language()
async def _song(_, m: types.Message):
    query = None
    if len(m.command) > 1:
        query = m.text.split(None, 1)[1]
    elif m.reply_to_message:
        query = m.reply_to_message.text or m.reply_to_message.caption

    if not query:
        return await m.reply_text(
            m.lang.get("song_usage", "❓ Usage: /song [song name or YouTube link]")
        )

    sent = await m.reply_text(m.lang.get("song_searching", "🔍 Searching..."))
    track = await yt.search(query, sent.id)
    if not track:
        return await sent.edit_text(
            m.lang.get("song_not_found", "❌ No results found for that.")
        )

    await sent.edit_text(
        m.lang.get("song_downloading", "⏳ Downloading <b>{0}</b>...").format(track.title)
    )
    file_path = await yt.download(track.id, progress_msg=sent, lang=m.lang)
    if not file_path:
        return await sent.edit_text(
            m.lang.get("song_failed", "❌ Couldn't download that song. Try another one.")
        )

    try:
        await sent.edit_text(m.lang.get("song_uploading", "📤 Uploading..."))
        await app.send_audio(
            chat_id=m.chat.id,
            audio=file_path,
            title=track.title,
            performer=track.channel_name or "Mikasa Music Bot",
            duration=track.duration_sec,
            caption=m.lang.get("song_caption", "🎵 <b>{0}</b>\n\nRequested by {1}").format(
                track.title, m.from_user.mention
            ),
            reply_to_message_id=m.id,
        )
        await sent.delete()
    except Exception:
        await sent.edit_text(
            m.lang.get("song_failed", "❌ Couldn't download that song. Try another one.")
        )
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass
