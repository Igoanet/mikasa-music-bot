# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Buttons of the suggestion card (see helpers/_recs.py).

    recs play <seed> <video id> → play that song here, as if the tapping
                                  user had sent /play <title> (same admin /
                                  queue / assistant checks, same messages)
    recs more <seed> <page>     → flip the card to that page of three songs
                                  ("More Songs ?" = page + 1, "◀ Back" = page - 1)
"""

import re

from pyrogram import enums, errors, filters, types

from bobby import app, lang, logger
from bobby.helpers import _recs as recs
from bobby.plugins.play import play_hndlr

_VIDEO_ID = re.compile(r"[0-9A-Za-z_-]{11}")


async def _keep(*_args, **_kwargs) -> bool:
    """Stands in for Message.delete on the synthetic /play: the "delete
    commands" group setting must not wipe the card the user just tapped."""
    return True


@app.on_callback_query(filters.regex(r"^recs ") & ~app.bl_users)
@lang.language()
async def _recs_cb(_, query: types.CallbackQuery) -> None:
    parts = query.data.split()
    if len(parts) < 3:
        return await query.answer()
    action, arg = parts[1], parts[2]
    card = query.message
    if card is None or getattr(card, "empty", False):
        return await query.answer(
            query.lang.get("recs_expired", recs.DEFAULT_EXPIRED), show_alert=True
        )

    if action == "more":
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        items = await recs.items_for(arg)
        if not items:
            return await query.answer(
                query.lang.get("recs_expired", recs.DEFAULT_EXPIRED), show_alert=True
            )
        try:
            await query.answer()
        except errors.QueryIdInvalid:
            pass
        return await query.edit_message_reply_markup(
            reply_markup=recs.markup(items, arg, page, query.lang)
        )

    if action != "play":
        return await query.answer()
    # current cards carry the seed so the tapped song can be looked up by
    # id; pre-change cards still in the wild carry only the video id
    if len(parts) >= 4:
        seed, vid = parts[2], parts[3]
    else:
        seed, vid = "", parts[2]
    if not _VIDEO_ID.fullmatch(vid):
        return await query.answer()

    try:
        await query.answer(query.lang.get("recs_picked", recs.DEFAULT_PICKED))
    except errors.QueryIdInvalid:
        pass  # tapped long ago — still honour the pick

    # Hand the pick to the real /play handler through a synthetic command
    # message: the tapping user is its author, the card is what the status
    # reply quotes. Every gate (admin-only play, queue limit, assistant join,
    # duration cap) and every message stays exactly the /play ones.
    logger.info("recs: %s picked %s in %s", query.from_user.id, vid, card.chat.id)

    # Play the pick as a TEXT query, not the YouTube URL: text flows through
    # the normal search -> catalogue-mirror pipeline, so a suggestion keeps
    # playing even when direct YouTube downloads are bot-blocked (a URL pick
    # was a straight shot into the blocked tier = the dead-button bug).
    item = None
    if seed:
        for it in await recs.items_for(seed):
            if it.get("id") == vid:
                item = it
                break
    if item:
        query_text = f"{item['title']} {item.get('artists') or ''}".strip()
        fake = types.Message(
            client=app,
            id=card.id,
            chat=card.chat,
            from_user=query.from_user,
            date=card.date,
            message_thread_id=card.message_thread_id,
            text=f"/play {query_text}",
            command=["play", query_text],
        )
    else:
        # stale card (cache evicted / refetch empty) — old URL behaviour
        url = f"https://www.youtube.com/watch?v={vid}"
        text = f"/play {url}"
        fake = types.Message(
            client=app,
            id=card.id,
            chat=card.chat,
            from_user=query.from_user,
            date=card.date,
            message_thread_id=card.message_thread_id,
            text=text,
            entities=[
                types.MessageEntity(
                    type=enums.MessageEntityType.URL,
                    offset=text.index(url),
                    length=len(url),
                )
            ],
            command=["play", url],
        )
    fake.delete = _keep
    fake.skip_live_probe = True  # a song off the card is never a live feed
    await play_hndlr(app, fake)
