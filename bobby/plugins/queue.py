# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import filters, types

from bobby import app, config, db, lang, queue, thumb
from bobby.helpers._selfdel import clean_reply
from bobby.helpers import Track, buttons


@app.on_message(filters.command(["queue", "playing"]) & filters.group & ~app.bl_users)
@lang.language()
async def _queue_func(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await clean_reply(m, m.lang["not_playing"])

    _reply = await clean_reply(m, m.lang["queue_fetching"], preserve=True)
    try:
        _queue = queue.get_queue(m.chat.id)
        _media = _queue[0]
        _thumb = (
            await thumb.generate(_media)
            if isinstance(_media, Track)
            else config.DEFAULT_THUMB
        ) if config.THUMB_GEN else None
        _text = m.lang["queue_curr"].format(
            _media.url,
            _media.title[:50],
            _media.duration,
            _media.user,
        )
        _queue.pop(0)

        if _queue:
            # Upcoming list: text only, no buttons (owner 2026-10-18).  The
            # count line makes the length obvious at a glance, and the list
            # folds into an expandable quote block so a long queue does not
            # bury the chat.
            _ups = min(len(_queue), 15)
            _more = len(_queue) - _ups
            _text += "\n\n<b>Up next \u2014 %d song%s</b>" % (
                len(_queue), "" if len(_queue) == 1 else "s"
            )
            _text += "\n<blockquote expandable>"
            for i, media in enumerate(_queue[:_ups], start=2):
                _text += m.lang["queue_item"].format(
                    i, media.title, media.duration
                )
            _text += "</blockquote>"
            if _more > 0:
                _text += "\n<i>\u2026 and %d more</i>" % _more

        if thumb:
            await _reply.edit_media(
                media=types.InputMediaPhoto(
                    media=_thumb,
                    caption=_text,
                ),
            )
        else:
            await _reply.edit_text(
                text=_text,
            )
    except Exception:
        try:
            await _reply.delete()
        except Exception:
            pass
        raise
