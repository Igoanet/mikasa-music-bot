# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import random
from collections import deque

from pyrogram import filters, types

from bobby import app, db, lang, queue
from bobby.helpers import can_manage_vc


@app.on_message(filters.command(["shuffle", "mix"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _shuffle(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    items = queue.get_queue(m.chat.id)
    if len(items) < 3:
        return await m.reply_text(
            m.lang.get(
                "shuffle_empty",
                "❌ Not enough tracks in the queue to shuffle.",
            )
        )

    # keep the currently playing track in place, shuffle the rest
    upcoming = items[1:]
    random.shuffle(upcoming)
    queue.queues[m.chat.id] = deque([items[0], *upcoming])

    await m.reply_text(
        m.lang.get("shuffle_done", "🔀 Queue shuffled — {0} tracks mixed by {1}.").format(
            len(upcoming), m.from_user.mention
        )
    )
