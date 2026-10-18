# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import re
from pathlib import Path

from pyrogram import filters, types

from bobby import anon, app, config, db, lang, logger, queue, tg, yt
from bobby.helpers import buttons, utils
from bobby.helpers._play import checkUB

_YT_ID = re.compile(r"[0-9A-Za-z_-]{11}")


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"
    text = text[:1948] + "</blockquote>"
    return text

@app.on_message(
    filters.command(["play", "playforce", "vplay", "vplayforce"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@checkUB
async def play_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str = None,
    query: str = "",
) -> None:
    if not getattr(m, "autoplay", False):
        # a real request always wins over a suggestion card or an autoplay
        # pick that is still being looked up in the background
        from bobby.helpers import _recs as recs

        recs.cancel(m.chat.id)
    # No "searching" notice: go straight to a playback status, so the
    # request reads as streaming rather than a lookup (2026-09-30).
    sent = await m.reply_text(m.lang["play_3"])
    file = None
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(m.reply_to_message, sent)

    elif m3u8:
        file = await tg.process_m3u8(url, sent.id, video)

    elif url:
        if "playlist" in url:
            await sent.edit_text(m.lang["playlist_fetch"])
            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT, mention, url, video
            )

            if not tracks:
                return await sent.edit_text(m.lang["playlist_error"])

            file = tracks[0]
            tracks.remove(file)
            file.message_id = sent.id
        else:
            # live streams can't be downloaded — resolve the feed URL instead;
            # a plain video link builds its Track directly from the URL
            # (searching YouTube for a raw link string returns nothing).
            # A song picked from the suggestion card is never a live feed,
            # so that path skips the multi-second yt-dlp probe.
            file = (
                (
                    None
                    if getattr(m, "skip_live_probe", False)
                    else await yt.get_live(url, sent.id, video)
                )
                or await yt.track_from_url(url, sent.id, video)
                or await yt.search(url, sent.id, video=video)
            )

        if not file:
            logger.info(
                "play: nothing found for url=%r in chat %s", url, m.chat.id
            )
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    elif query:
        # autoplay resolved and validated its track before announcing it —
        # searching the same words again could queue a different upload
        # (even the song that just finished), so reuse that exact track.
        file = getattr(m, "autoplay_track", None)
        if file is not None:
            file.message_id = sent.id
        else:
            file = await yt.search(query, sent.id, video=video)
        if not file:
            logger.info(
                "play: nothing found for query=%r in chat %s", query, m.chat.id
            )
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    if not file:
        return await sent.edit_text(m.lang["play_usage"])

    # get_live keeps a LIVE metadata track even when every extracted feed is
    # unreadable, so an ended/private/broken broadcast is reported explicitly
    # instead of being queued as if it were an ordinary VOD.
    if file.duration == "🔴 LIVE" and not file.file_path:
        logger.info("play: live source unavailable for %s", file.id)
        return await sent.edit_text(
            m.lang["play_not_found"].format(config.SUPPORT_CHAT)
        )

    if file.duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60)
        )

    if await db.is_logger():
        await utils.play_log(m, sent.link, file.title, file.duration)

    # suggestion card seed: a single YouTube track (Telegram files, m3u8 feeds
    # and playlists have nothing to relate). Pinned NOW because play_source
    # may later swap the track's identity to a catalogue mirror; the card
    # itself is posted when this track ends and nothing follows it (see
    # Calls.play_next), not while it is starting.
    if not tracks and not media and not m3u8 and _YT_ID.fullmatch(file.id or ""):
        file.seed = file.id

    file.user = mention
    claim = getattr(m, "autoplay_claim", None)
    if claim is not None and not await claim():
        # a real /play, /stop or autoplay-off landed while this background
        # pick was being prepared — that request owns the chat now.  Checked
        # here because nothing awaits between this point and the queue.
        logger.info("autoplay: dropped %s in %s (cancelled)", file.id, m.chat.id)
        return await sent.delete()
    if force:
        queue.force_add(m.chat.id, file)
    else:
        position = queue.add(m.chat.id, file)

        if position != 0 or await db.get_call(m.chat.id):
            # A YouTube live feed is signed and expires.  Keep the LIVE
            # identity in the queue but resolve its direct feed when it
            # reaches the voice call (play_source's live branch).
            if file.duration == "🔴 LIVE":
                file.file_path = None
            await sent.edit_text(
                m.lang["play_queued"].format(
                    # +1 counts the track that is already playing as #1, so
                    # this matches the numbering /queue shows (2026-10-05).
                    position + 1,
                    file.url,
                    file.title,
                    file.duration,
                    m.from_user.mention,
                    len(queue.get_queue(m.chat.id)),
                ),
            )
            if tracks:
                added = playlist_to_queue(m.chat.id, tracks)
                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    if not file.file_path:
        # the exists() probe only gates the status text — play_source itself
        # decides cache vs stream vs download, so no behavioral race here
        if not Path(f"downloads/{file.id}.{'mp4' if video else 'webm'}").exists():
            pass  # download notice suppressed (2026-09-30)
        # play_source: cached file → instant stream URL → full download
        file.file_path = await yt.play_source(
            file, video=video, progress_msg=sent, lang=m.lang
        )

    if not file.file_path:
        logger.info("play: source resolution failed for %s", file.id)
        return await sent.edit_text(
            m.lang["play_not_found"].format(config.SUPPORT_CHAT)
        )

    if claim is not None and not await claim(final=True):
        # resolving the source can take a while; a /stop or a real /play that
        # landed meanwhile owns the chat, so this pick must leave the queue
        # instead of reviving playback behind them
        logger.info("autoplay: dropped %s in %s (cancelled late)", file.id, m.chat.id)
        queue.drop_item(m.chat.id, file)
        return await sent.delete()

    await anon.play_media(chat_id=m.chat.id, message=sent, media=file)
    if not tracks:
        return
    added = playlist_to_queue(m.chat.id, tracks)
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
    )
