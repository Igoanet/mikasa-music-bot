# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import asyncio
import os
import uuid
from collections import defaultdict

from pyrogram import filters, types

from bobby import anon, app, db, lang, queue
from bobby.helpers import can_manage_vc

# one speed change at a time per chat: a second request queues behind the encode
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
ENCODE_TIMEOUT = 240  # s — a 4x-realtime encode of the longest sane track; live inputs never end


@app.on_message(filters.command(["speed", "playback"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _speed(_, m: types.Message):
    usage = m.lang.get(
        "speed_usage",
        "❓ Usage: /speed [0.5-2.0] — e.g. <code>/speed 1.5</code>",
    )
    if len(m.command) < 2:
        return await m.reply_text(usage)

    try:
        speed = float(m.command[1].replace("x", ""))
    except ValueError:
        return await m.reply_text(usage)
    if not 0.5 <= speed <= 2.0:
        return await m.reply_text(usage)
    speed = round(speed, 2)

    async with _locks[m.chat.id]:
        await _apply(m, speed)


async def _apply(m: types.Message, speed: float) -> None:
    chat_id = m.chat.id
    failed = m.lang.get("speed_failed", "❌ Couldn't change the speed right now.")
    if not await db.get_call(chat_id):
        return await m.reply_text(m.lang["not_playing"])
    if not await db.playing(chat_id):
        return await m.reply_text(m.lang["play_already_paused"])

    media = queue.get_current(chat_id)
    if not media or not media.file_path:
        return await m.reply_text(failed)
    if getattr(media, "video", False) or not (media.source_duration_sec or media.duration_sec):
        # video would come back audio-only; a live/endless input would encode forever
        return await m.reply_text(m.lang.get(
            "speed_unsupported", "❌ /speed works for audio tracks with a known length, not video or live streams.",
        ))
    cur_speed = media.speed or 1.0
    if speed == cur_speed:
        return await m.reply_text(m.lang.get(
            "speed_same", "ℹ️ Already playing at <b>{0}x</b>.",
        ).format(speed))

    sent = await m.reply_text(m.lang.get("processing", "Processing..."))

    # py-tgcalls can't take audio filters at stream time, so bake a tempo
    # variant and restart the stream at the scaled position.  ALWAYS cut it
    # from the untempoed original: cutting from the previous variant
    # compounded the speeds (1.2 then 1.0 stayed at 1.2x; 0.8 after 1.2 came
    # out as 0.96x) and every pass re-encoded the last one's artefacts.
    src = media.source_path or media.file_path
    src_duration = media.source_duration_sec or media.duration_sec

    if speed == 1.0:
        out_path = src  # back to the original as it is — no re-encode
    else:
        # unique name: the same song can play in another chat, and "-y" over a
        # file ffmpeg is still reading for the call would cut the sound
        out_path = f"downloads/speed_{media.id}_{speed}_{uuid.uuid4().hex[:6]}.ogg"
        if not await _encode(src, speed, out_path):
            return await sent.edit_text(failed)

    # the encode took a while: only switch if THIS track is still the one
    # playing (not stopped, skipped or paused meanwhile — a restart would
    # resume a paused call)
    if (queue.get_current(chat_id) is not media or not await db.get_call(chat_id)
            or not await db.playing(chat_id)):
        if out_path != src:
            queue.purge_file(out_path)
        return await sent.edit_text(m.lang.get(
            "speed_stale", "ℹ️ The song changed while I was working — speed not applied.",
        ))

    # position in the tempo file = original position / speed (sampled now, not
    # before the encode, so we resume where the listeners actually are)
    orig_pos = (media.time or 1) * cur_speed
    pos = max(1, int(orig_pos / speed))
    old_path = media.file_path
    media.source_path = src
    media.source_duration_sec = src_duration
    media.speed = speed
    media.file_path = out_path
    media.duration_sec = int(src_duration / speed)

    await anon.play_media(chat_id, sent, media, pos)
    if queue.get_current(chat_id) is not media:
        # play_media reported the failure itself and moved on; nothing to add
        return
    media.time = pos
    if old_path not in (src, out_path):
        queue.purge_file(old_path)  # the superseded tempo variant
    await sent.edit_text(
        m.lang.get("speed_done", "⏩ Playback speed set to <b>{0}x</b> by {1}.").format(
            speed, m.from_user.mention
        )
    )


async def _encode(src: str, speed: float, out_path: str) -> bool:
    """Tempo variant of `src` (a local file or the RAM-spool URL) as Opus in Ogg —
    whatever the source container, so an .mp3/.m4a original never picks a muxer
    that cannot hold the codec.  Niced and capped at 2 threads: a playing song
    always wins the CPU."""
    proc = await asyncio.create_subprocess_exec(
        "nice", "-n", "10", "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
        "-threads", "2", "-i", str(src),
        "-vn", "-filter:a", f"atempo={speed}",
        "-c:a", "libopus", "-b:a", "160k", "-vbr", "on", "-f", "ogg",
        out_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), ENCODE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    ok = proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    if not ok:
        try:
            os.remove(out_path)
        except OSError:
            pass
    return ok
