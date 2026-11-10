# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import random
from collections import deque

from pyrogram import filters, types

from bobby import app, db, lang, queue
from bobby.helpers import can_manage_vc


# Command removed by paneer request
# @app.on_message(filters.command(["shuffle", "mix"]) & filters.group & ~app.bl_users)
# @lang.language()
# @can_manage_vc
# async def _shuffle(_, m: types.Message):
#     ...
