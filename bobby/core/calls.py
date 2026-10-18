# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import asyncio
import json
import os

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError,
                      TransportParseException)
from pyrogram.errors import (ChatAdminRequired, ChatSendMediaForbidden,
                             FloodWait,
                             ChatSendPhotosForbidden, MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from bobby import (app, config, db, lang, logger,
                   queue, thumb, userbot, yt)
from bobby.core.call_lifecycle import CallLifecycle, leave_assistant
from bobby.core import disco
from bobby.core import pulse
from bobby.helpers import Media, Track, buttons

def _describe_transport(params: str | None) -> str:
    """'udp 91.108.x.x:1400 host, tcp ...' from a JoinGroupCall answer —
    addresses only, never the ICE credentials that sit next to them."""
    if not params:
        return "no params"
    data = json.loads(params)
    if data.get("stream") or data.get("rtmp"):
        return "stream/rtmp mode (no WebRTC transport)"
    cands = (data.get("transport") or {}).get("candidates") or []
    if not cands:
        return "no ICE candidates in answer"
    parts = []
    for c in cands[:6]:
        parts.append(
            f"{c.get('protocol', '?')} {c.get('ip', '?')}:{c.get('port', '?')}"
            + (f" {c['type']}" if c.get("type") else "")
            + (f"/{c['tcptype']}" if c.get("tcptype") else "")
        )
    if len(cands) > 6:
        parts.append(f"+{len(cands) - 6} more")
    return ", ".join(parts)

def _ffmpeg_params(media: Media | Track, seek_time: int) -> str | None:
    """ffmpeg input options for this playback.

    Pacing: NONE, on purpose. ntgcalls is the clock of this pipeline — it
    pulls exactly 10 ms of PCM at a time from ffmpeg's stdout, so ffmpeg
    must simply keep that 64 KB pipe full and block on it, the way
    py-tgcalls has always run it. Any producer-side rate limit ("-re",
    readrate) throttles ffmpeg to ~1x and lets the cushion in the pipe
    drain, which is exactly how a small hiccup becomes an audible gap plus
    a burst catch-up (the "speed-up" listeners describe). Network jitter is
    absorbed one layer up: play_source hands remote audio over as a local
    RAM-spool URL (bobby/core/spool.py), so ffmpeg only ever reads
    127.0.0.1; live/HLS streams stay direct."""
    parts = []
    # A deeper demuxer queue absorbs a short scheduling stall (the pipe holds
    # only ~330 ms, and a 0.5s main-loop block drained it — 2026-09-30).
    parts.append("-thread_queue_size 1024")
    if getattr(media, "video", False):
        # video decode defaults to ALL cores — on a shared host that
        # starves the audio encoder thread and the VOICE breaks first.
        # 2 threads decode 720p many times faster than realtime anyway;
        # the audio always keeps its CPU.
        parts.append("-threads 2")
    if str(media.file_path).startswith("http"):
        # wider probe window + timestamp repair for streamed inputs
        # (default probing on a slow link stutters right at the start).
        # No manual -reconnect here: py-tgcalls build_command appends the
        # reconnect flags for URL inputs itself.
        parts.append("-probesize 2M -analyzeduration 1M")
    if seek_time > 1:
        parts.append(f"-ss {seek_time}")
    return " ".join(parts) or None

class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self._joining: set[int] = set()  # chats with a JoinGroupCall in flight
        self._lifecycle = CallLifecycle()

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=True)
        try:
            return await client.pause(chat_id)
        except (ConnectionNotFound, exceptions.NotInCallError):
            await self.stop(chat_id)

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=False)
        try:
            return await client.resume(chat_id)
        except (ConnectionNotFound, exceptions.NotInCallError):
            await self.stop(chat_id)

    @staticmethod
    def _log_leave(stage: str, chat_id: int, attempt: int, detail: str) -> None:
        logger.warning(
            "vc cleanup %s in %s (attempt %s): %s",
            stage, chat_id, attempt, detail,
        )

    async def _leave_assistant(self, client, chat_id: int) -> bool:
        if not await leave_assistant(
            client,
            chat_id,
            self._log_leave,
            settle_delay=1.0,
        ):
            logger.error("vc cleanup could not confirm assistant leave in %s", chat_id)
            return False
        logger.info("vc assistant leave verified in %s", chat_id)
        return True

    @staticmethod
    def _is_live(media: Media | Track) -> bool:
        """Recognise live metadata regardless of the display-marker version."""
        return (
            getattr(media, "duration", None) in {"LIVE", "🔴 LIVE"}
            or getattr(media, "view_count", None) == "LIVE"
        )

    async def _resolve_live_source(
        self,
        media: Media | Track,
        *,
        video: bool = False,
        progress_msg=None,
        lang=None,
    ) -> str | None:
        """Resolve the current feed for this exact live broadcast.

        A signed live URL can expire while a track waits in the queue. Never
        trust a prefetched path and never send a live track through
        ``play_source``: its ordinary failure path is deliberately allowed to
        download, search a catalogue mirror, or adopt another upload.
        """
        track_id = getattr(media, "id", None)
        media.file_path = None
        resolver = getattr(yt, "resolve_play_source", None)
        if resolver is not None:
            resolved = await resolver(
                media,
                video=video,
                progress_msg=progress_msg,
                lang=lang,
            )
        else:
            get_live = getattr(yt, "get_live", None)
            if get_live is None:
                raise LookupError("live source resolver unavailable")
            url = getattr(media, "url", None) or (
                getattr(yt, "base", "https://www.youtube.com/watch?v=")
                + str(media.id)
            )
            resolved = await get_live(
                url,
                getattr(media, "message_id", 0),
                video,
            )

        if getattr(media, "id", track_id) != track_id:
            media.id = track_id
            media.file_path = None
            raise LookupError("live resolver changed track identity")
        if isinstance(resolved, str):
            path = resolved
        else:
            resolved_id = getattr(resolved, "id", None)
            if resolved is not None and resolved_id not in (None, media.id):
                raise LookupError("live resolver changed track identity")
            path = (
                getattr(resolved, "file_path", None)
                if resolved is not None
                else getattr(media, "file_path", None)
            )
            if resolved is not None:
                # get_live returns fresh metadata for the same broadcast. Do
                # not copy its id/url: those fields are the queue identity.
                for field in ("title", "thumbnail", "duration", "duration_sec"):
                    value = getattr(resolved, field, None)
                    if value is not None:
                        setattr(media, field, value)
                media.view_count = "LIVE"
        media.file_path = path
        return path

    async def _recover_track_failure(
        self,
        chat_id: int,
        message: Message,
        generation: int,
    ) -> bool:
        """Skip one failed source without throwing away unrelated queued songs.

        A process can disappear between py-tgcalls' spawn and cleanup.  That
        is a per-install failure, not an instruction to call ``stop()``:
        stop clears the complete queue.  The one iterative ``play_next``
        driver owns the normal generation-checked transition; calling it
        here would recurse once for every installable-but-unplayable item.

        ``False`` is deliberately a recoverable per-track outcome, not an
        exception.  It lets both an initial request and an automatic advance
        hand control to that same bounded driver.
        """
        if not await self._lifecycle.current(chat_id, generation):
            return True
        try:
            _lang = await lang.get_lang(chat_id)
            await message.edit_text(_lang.get(
                "play_skip_failed",
                "⚠️ <b>Skipped</b>\n\nI couldn't get that one — playing the next song in the queue.",
            ))
        except Exception:
            # A deleted status message must not prevent the queue transition.
            pass
        return False

    async def stop(
        self,
        chat_id: int,
        expected_generation: int | None = None,
        assistant_client=None,
    ) -> bool:
        # Exit cleanup passes the captured PyTgCalls binding before doing any
        # asynchronous work.  Normal command paths retain the historical
        # lookup (which may allocate an assistant for a new play request).
        client = (
            assistant_client
            if assistant_client is not None
            else await db.get_assistant(chat_id)
        )

        async def _cleanup() -> None:
            try:
                old_items = queue.get_queue(chat_id)
                # the song is over: take its now-playing panel down with it,
                # cleanly (owner 2026-10-07)
                try:
                    _cur = old_items[0] if old_items else None
                    _mid = getattr(_cur, "message_id", 0) if _cur else 0
                    if _mid:
                        await app.delete_messages(
                            chat_id=chat_id, message_ids=_mid, revoke=True,
                        )
                        _cur.message_id = 0
                except Exception:
                    pass
                queue.clear(chat_id)
                # free every file this queue held (purge_file skips files
                # another chat still references)
                for item in old_items:
                    queue.purge_item(item)
            except Exception as ex:
                logger.warning(
                    "vc cleanup queue reset failed in %s: %s",
                    chat_id, type(ex).__name__,
                )
            finally:
                try:
                    await db.remove_call(chat_id)
                    await db.set_loop(chat_id, 0)
                except Exception as ex:
                    logger.warning(
                        "vc cleanup state reset failed in %s: %s",
                        chat_id, type(ex).__name__,
                    )
                finally:
                    # leave_assistant verifies Telegram participant absence and
                    # uses a fresh direct LeaveGroupCall when native teardown
                    # did not remove this assistant.  Never close/discard the
                    # group voice chat: it belongs to everyone, not this
                    # assistant.
                    await self._leave_assistant(client, chat_id)

        return await self._lifecycle.terminal(
            chat_id, _cleanup, expected_generation,
        )

    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
    ) -> None:
        """Install a fresh generation for a direct playback request."""
        generation = await self._lifecycle.start(chat_id)
        if generation is None:
            return
        failed = await self._play_media(
            chat_id, message, media, seek_time, generation
        )
        if failed is False:
            await self.play_next(chat_id, generation)

    async def _play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int,
        generation: int,
        *,
        live_attempt: int = 0,
    ) -> bool | None:
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)
        _thumb = (
            await thumb.generate(media)
            if isinstance(media, Track)
            else config.DEFAULT_THUMB
        ) if config.THUMB_GEN else None

        if not await self._lifecycle.current(chat_id, generation):
            return
        if self._is_live(media):
            # The source installed below must always come from a fresh live
            # resolver, even if misc.py prefetched a signed URL for this item.
            try:
                media.file_path = await self._resolve_live_source(
                    media,
                    video=getattr(media, "video", False),
                    progress_msg=message,
                    lang=_lang,
                )
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                media.file_path = None
                logger.warning(
                    "live source unavailable for %s: %s",
                    getattr(media, "id", "?"), type(ex).__name__,
                )
        if not media.file_path:
            if self._is_live(media):
                if live_attempt < 1:
                    # A metadata/feed probe can fail transiently before native
                    # installation; refresh this same broadcast once, never
                    # recurse indefinitely or switch track identity.
                    return await self._play_media(
                        chat_id, message, media, seek_time, generation,
                        live_attempt=live_attempt + 1,
                    )
                logger.warning(
                    "live source unavailable after refresh for %s",
                    getattr(media, "id", "?"),
                )
                return await self._recover_track_failure(
                    chat_id, message, generation,
                )
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            return False

        # mark the join as in flight so the CLOSED_VOICE_CHAT update guard
        # (see decorators) ignores Telegram's false "closed" events mid-join
        self._joining.add(chat_id)
        stream = types.MediaStream(
            media_path=media.file_path,
            # HIGH = 48kHz stereo — the RIGHT ceiling: Opus physically caps
            # at 48kHz (RFC 6716), so STUDIO's 96kHz just doubles PCM
            # resample work on shared CPU for ZERO audible gain (that extra
            # CPU was part of the stutter). AnonXMusic ships HIGH too.
            audio_parameters=types.AudioQuality.HIGH,
            video_parameters=types.VideoQuality.HD_720p,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if media.video
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=_ffmpeg_params(media, seek_time),
        )
        async def _native_play() -> None:
            # hard ceiling: pytgcalls can hang FOREVER on a zombie group call
            # (left behind when the bot was restarted mid-call — Telegram
            # answers GROUPCALL_FORBIDDEN and pytgcalls just retries
            # internally, never raising). wait_for turns the silent hang
            # into a TimeoutError we can recover from.
            await asyncio.wait_for(
                client.play(
                    chat_id=chat_id,
                    stream=stream,
                    # auto_start: the assistant starts the voice chat itself
                    # when the group has none running — the classic cause of
                    # JoinGroupCall retrying until timeout
                    config=types.GroupCallConfig(auto_start=True),
                ),
                timeout=45,
            )
            # play() can return after a SILENT failure (joined a dead call,
            # or the shell-spawn deadlock in ntgcalls <= 3.0.0rc1 killed the
            # ffmpeg decode). The "playing" message must never post unless
            # the call connection actually exists — verify via the binding
            # registry, bounded, so a stuck/failed lookup lands on the
            # retryable TimeoutError path instead of hanging play_media.
            binding = getattr(client, "_binding", None)
            if binding is not None:
                try:
                    active = await asyncio.wait_for(binding.calls(), timeout=10)
                except Exception as ex:
                    raise TimeoutError(f"post-play check failed: {ex}") from ex
                if chat_id not in active:
                    raise TimeoutError("play() returned but no active call")

        try:
            for attempt in (1, 2):
                try:
                    installed = await self._lifecycle.install(
                        chat_id, generation, _native_play,
                    )
                    if not installed:
                        return
                    break
                except TimeoutError:
                    if not await self._lifecycle.current(chat_id, generation):
                        return
                    if attempt == 2:
                        raise
                    reason = "timeout"
                except Exception as ex:
                    if not await self._lifecycle.current(chat_id, generation):
                        return
                    # only a zombie group call (GROUPCALL_FORBIDDEN — left
                    # behind when the bot was restarted mid-call) is
                    # recoverable here; anything else goes straight to the
                    # outer handlers
                    if attempt == 2 or "GROUPCALL_FORBIDDEN" not in str(ex):
                        raise
                    reason = str(ex)[:80]
                # Recovery here leaves this assistant only; no playback error
                # may discard/end a VC shared with other participants.
                try:
                    if not await self._lifecycle.recover(
                        chat_id, generation,
                        lambda: self._leave_assistant(client, chat_id),
                    ):
                        if not await self._lifecycle.current(chat_id, generation):
                            return
                        raise TimeoutError("assistant cleanup failed")
                except Exception as ex:
                    logger.error(
                        "stale-call cleanup failed in %s: %s",
                        chat_id, type(ex).__name__,
                    )
                    raise TimeoutError("stale-call cleanup failed") from ex
                logger.warning(
                    "join failed in %s (%s); assistant left, retrying",
                    chat_id, reason,
                )
                await asyncio.sleep(4)
            if not await self._lifecycle.current(chat_id, generation):
                return
            # measure this play: source underrun vs consumer stall, per chat
            pulse.watch(chat_id, media.id, media.file_path, media.duration_sec)
            if not seek_time:
                media.time = 1
                await db.add_call(chat_id)
                text = _lang["play_media"].format(
                    media.url,
                    media.title,
                    media.duration,
                    media.user,
                )
                from bobby.core.disco import progress_bar as _bar
                keyboard = buttons.controls(
                    chat_id, status=_bar(0, getattr(media, "duration_sec", 0)),
                    autoplay=await db.get_autoplay(chat_id),
                    _lang=_lang, is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),)
                _panel_id = getattr(message, "id", 0)
                try:
                    if _thumb:
                        await message.edit_media(
                            media=InputMediaPhoto(
                                media=_thumb,
                                caption=text,
                            ),
                            reply_markup=keyboard,
                        )
                    else:
                        await message.edit_text(text, reply_markup=keyboard)
                except (ChatSendMediaForbidden, ChatSendPhotosForbidden, MessageIdInvalid):
                    if _thumb:
                        sent = await app.send_photo(
                            chat_id=chat_id,
                            photo=_thumb,
                            caption=text,
                            reply_markup=keyboard,
                        )
                    else:
                        sent = await app.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=keyboard,
                        )
                    media.message_id = sent.id
                    _panel_id = sent.id
                # the panel's buttons cycle colours while this call is live
                try:
                    disco.register(chat_id, _panel_id, keyboard,
                                   getattr(media, "duration_sec", 0))
                except Exception:
                    pass
        except FileNotFoundError:
            if self._is_live(media):
                if live_attempt < 1:
                    return await self._play_media(
                        chat_id, message, media, seek_time, generation,
                        live_attempt=live_attempt + 1,
                    )
                logger.warning(
                    "live source unavailable after refresh for %s",
                    getattr(media, "id", "?"),
                )
                return await self._recover_track_failure(
                    chat_id, message, generation,
                )
            # the cached file was reaped between the probe and playback —
            # re-resolve the SAME track once (stream URL or fresh download)
            # instead of skipping a song the user asked for; the one-shot
            # flag makes a pathological delete-loop impossible
            if not getattr(media, "_reresolved", False):
                media._reresolved = True
                logger.warning(
                    "local file vanished for %s; re-resolving", media.id
                )
                try:
                    media.file_path = await yt.play_source(
                        media, video=getattr(media, "video", False)
                    )
                except Exception:
                    media.file_path = None
                if media.file_path:
                    return await self._play_media(
                        chat_id, message, media, seek_time, generation,
                    )
            return await self._recover_track_failure(
                chat_id, message, generation
            )
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id, generation)
            await message.edit_text(_lang["error_no_call"])
        except exceptions.NoAudioSourceFound:
            if self._is_live(media):
                if live_attempt < 1:
                    # A signed feed can expire between resolution and native
                    # install. Retry this same broadcast once; importantly,
                    # _play_media will resolve a fresh feed before install.
                    return await self._play_media(
                        chat_id, message, media, seek_time, generation,
                        live_attempt=live_attempt + 1,
                    )
                logger.warning(
                    "live source unavailable after refresh for %s",
                    getattr(media, "id", "?"),
                )
                return await self._recover_track_failure(
                    chat_id, message, generation,
                )
            if media.file_path and str(media.file_path).startswith("http"):
                # the CDN link died between validation and play — retry the
                # SAME track once via the download path instead of skipping
                logger.warning(
                    "stream url failed for %s; retrying via download", media.id
                )
                media.file_path = await yt.download_with_fallback(
                    media, video=getattr(media, "video", False)
                )
                if media.file_path:
                    return await self._play_media(
                        chat_id, message, media, seek_time, generation,
                    )
            return await self._recover_track_failure(
                chat_id, message, generation
            )
        except ChatAdminRequired:
            # auto_start=True means py-tgcalls tries to CREATE the voice
            # chat, which needs the assistant to have the 'Manage Voice
            # Chats' admin right. No right + no running VC = unjoinable;
            # this must surface as a clear message, not a frozen
            # "Downloading..." (the retry loop's generic handler re-raises
            # it here — only GROUPCALL_FORBIDDEN/timeout are recoverable).
            logger.warning(
                "can't auto-start VC in %s: assistant is not admin", chat_id
            )
            await self.stop(chat_id, generation)
            await message.edit_text(
                _lang.get("error_vc_admin", _lang["error_no_call"])
            )
        except TimeoutError as e:
            # join failed even after the retry: no voice chat the assistant
            # can start/join, or it's restricted in this group
            logger.error("join failed in %s: %s: %s", chat_id, type(e).__name__, e)
            await self.stop(chat_id, generation)
            await message.edit_text(
                _lang.get("error_vc_join", _lang["error_tg_server"])
            )
        except (ConnectionError, ConnectionNotFound, TelegramServerError,
                TransportParseException) as e:
            logger.error("call error in %s: %s: %s", chat_id, type(e).__name__, e)
            return await self._recover_track_failure(
                chat_id, message, generation
            )
        except ProcessLookupError:
            # asyncio raises this when a native ffmpeg child exits in the
            # narrow interval before its owner tries to signal it.  The VPS
            # recorded this after a successful prior leave; it is not proof
            # of a Telegram server failure, and it must not clear a whole
            # multi-track queue.
            logger.exception(
                "play process disappeared in %s; preserving remaining queue",
                chat_id,
            )
            return await self._recover_track_failure(
                chat_id, message, generation
            )
        except RTMPStreamingUnsupported:
            await self.stop(chat_id, generation)
            await message.edit_text(_lang["error_rtmp"])
        except FloodWait as e:
            # Telegram rate-limited a MESSAGE EDIT -- not the audio.  The
            # track itself is fine, and treating this as a failed track is
            # exactly what made songs auto-skip while the disco panel edited
            # the same message (owner 2026-10-07).  Slow the panel instead.
            _wait = float(getattr(e, "value", 5) or 5)
            logger.warning(
                "message-edit flood in %s (wait %ss); keeping the track",
                chat_id, int(_wait),
            )
            try:
                disco.add_penalty(_wait)
            except Exception:
                pass
        except Exception as e:
            # last-resort net: an unexpected streaming error (e.g. a remote
            # source dying inside ffprobe) must never escape the handler and
            # freeze the status message again
            logger.exception(
                "unexpected play error in %s: %s: %s; preserving remaining queue",
                chat_id, type(e).__name__, e,
            )
            return await self._recover_track_failure(
                chat_id, message, generation
            )
        finally:
            self._joining.discard(chat_id)
        return True

    async def replay(
        self, chat_id: int, expected_generation: int | None = None,
    ) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        generation = await self._lifecycle.start(chat_id, expected_generation)
        if generation is None or media is None:
            return
        _lang = await lang.get_lang(chat_id)
        if not await self._lifecycle.current(chat_id, generation):
            return
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        failed = await self._play_media(chat_id, msg, media, 0, generation)
        if failed is False:
            await self.play_next(chat_id, generation)

    async def play_next(
        self,
        chat_id: int,
        expected_generation: int | None = None,
        *,
        stream_ended: bool = False,
    ) -> None:
        # Walk unavailable sources without one Python stack frame per item.
        # A queue loop gets at most one full failed round, never infinite retries.
        budget = max(1, len(queue.get_queue(chat_id)))
        for _ in range(budget):
            failed_generation = await self._advance_once(
                chat_id, expected_generation, stream_ended=stream_ended,
            )
            if failed_generation is None:
                return
            expected_generation = failed_generation
            stream_ended = False
        await self.stop(chat_id, expected_generation)

    async def _advance_once(
        self, chat_id: int, expected_generation: int | None = None,
        *, stream_ended: bool = False,
    ) -> int | None:
        generation = await self._lifecycle.claim_advance(
            chat_id, expected_generation, stream_ended=stream_ended,
        )
        if generation is None:
            return
        claimed = generation
        loop = await db.get_loop(chat_id)
        if not await self._lifecycle.current(chat_id, generation):
            # hand the claim back: it must never outlive this call, or the
            # next /skip is silently dropped (owner 2026-10-17)
            await self._lifecycle.release_advance(chat_id, claimed)
            return
        finished = None
        if loop == -1:
            # queue loop: rotate the finished track to the back instead of
            # dropping it — the queue repeats until /loop off or /stop
            if queue.queues[chat_id]:
                queue.queues[chat_id].rotate(-1)
            media = queue.get_current(chat_id)
        else:
            if loop:
                await db.set_loop(chat_id, loop - 1)
                return await self.replay(chat_id, generation)
            finished = queue.get_current(chat_id)
            media = queue.get_next(chat_id)
            # storage hygiene: a finished (non-looped) track never plays
            # again — delete its download before fetching the next one
            if finished is not None and finished is not media:
                queue.purge_item(finished)
        if not media:
            # the music stops here: offer what to play next, seeded by the
            # track that just ended (skipped or played out). A manual /stop
            # never comes this way, so it stays silent. Best-effort only —
            # The leave is mandatory and happens before even resolving the
            # language for the decorative recommendation card.
            seed = getattr(finished, "seed", None)
            # AUTOPLAY FIRST, LEAVE LAST (owner 2026-10-18): with autoplay on
            # the next related song starts while the assistant is still IN the
            # voice chat, so one song ending flows straight into the next.
            # Tearing down first used to leave an empty VC and the hand-off
            # could never resume from there.
            if seed and await db.get_autoplay(chat_id):
                try:
                    from bobby.helpers import _recs as recs  # lazy: needs bobby.app
                    _lang_ap = await lang.get_lang(chat_id)
                    if await recs.autoplay_now(chat_id, seed, _lang_ap):
                        logger.info(
                            "autoplay: next song started in %s - staying in VC",
                            chat_id,
                        )
                        return
                except Exception as ex:
                    logger.warning("autoplay hand-off failed in %s: %s: %s",
                                   chat_id, type(ex).__name__, ex)
            stopped = await self.stop(chat_id, generation)
            if not stopped:
                return
            if seed:
                try:
                    from bobby.helpers import _recs as recs  # lazy: needs bobby.app
                    _lang = await lang.get_lang(chat_id)
                    # autoplay already had its chance above; what is left is
                    # the suggestion card so the group can pick one itself.
                    recs.suggest(chat_id, seed, _lang)
                except Exception as ex:
                    logger.warning(
                        "recs: card not scheduled for %s: %s: %s",
                        chat_id, type(ex).__name__, ex,
                    )
            return
        started = await self._lifecycle.start(chat_id, generation)
        if started is None:
            await self._lifecycle.release_advance(chat_id, claimed)
            return
        generation = started
        try:
            if not await self._lifecycle.current(chat_id, generation):
                return
            if media.message_id:
                await app.delete_messages(
                    chat_id=chat_id,
                    message_ids=media.message_id,
                    revoke=True,
                )
                media.message_id = 0
        except Exception:
            pass

        _lang = await lang.get_lang(chat_id)
        if not await self._lifecycle.current(chat_id, generation):
            return
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_next"])
        if not self._is_live(media) and not media.file_path:
            # saavn tracks stream straight from the CDN; everything else
            # (and any stream failure) falls back to downloading
            try:
                media.file_path = await yt.play_source(
                    media, video=media.video, progress_msg=msg, lang=_lang
                )
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                # Resolver failures are per-track failures.  Above all, do
                # not leave this generation marked installing and strand the
                # "next" status message forever.
                logger.warning(
                    "play source failed for %s in %s: %s",
                    getattr(media, "id", "?"), chat_id, type(ex).__name__,
                )
                media.file_path = None
            if not await self._lifecycle.current(chat_id, generation):
                return
            if not media.file_path and not self._is_live(media):
                await msg.edit_text(
                    _lang.get(
                        "play_skip_failed",
                        "⚠️ <b>Skipped</b>\n\nI couldn't get that one — playing the next song in the queue.",
                    )
                )
                return generation

        # Live paths are signed and may have expired while this item waited
        # behind another track. _play_media resolves the same broadcast afresh
        # immediately before native installation, regardless of any prefetch.
        media.message_id = msg.id
        failed = await self._play_media(chat_id, msg, media, 0, generation)
        if failed is False:
            return generation

    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        if not pings:  # no assistants added yet
            return 0.0
        return round(sum(pings) / len(pings), 2)

    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.StreamEnded):
                if update.stream_type == types.StreamEnded.Type.AUDIO:
                    await self.play_next(update.chat_id, stream_ended=True)
            elif isinstance(update, types.ChatUpdate):
                if update.status in [
                    types.ChatUpdate.Status.KICKED,
                    types.ChatUpdate.Status.LEFT_GROUP,
                    types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ]:
                    # Telegram sometimes reports the voice chat closed while
                    # the assistant is still mid-join (JoinGroupCall retries);
                    # ignore it only while a join is genuinely in flight —
                    # once playing, the event is real and must tear down
                    if (
                        update.status == types.ChatUpdate.Status.CLOSED_VOICE_CHAT
                        and await self._lifecycle.installing(update.chat_id)
                    ):
                        logger.warning(
                            f"Ignoring CLOSED_VOICE_CHAT for {update.chat_id}: join in progress"
                        )
                        return
                    await self.stop(update.chat_id)

    async def add_client(self, ub) -> None:
        """Bind one assistant client to a PyTgCalls instance (keeps
        self.clients index-aligned with userbot.clients)."""
        # longer cache: repeat plays skip the slow FullChat/participant lookups
        client = PyTgCalls(ub, cache_duration=1800)
        await client.start()
        self.clients.append(client)
        await self.decorators(client)
        self._log_connection_changes(client)
        self._log_transport(client)

    @staticmethod
    def _log_transport(client: PyTgCalls) -> None:
        """Log WHICH relay a voice chat is served from at every join.

        Telegram hands the media-server ICE candidates back in the
        JoinGroupCall answer (ip:port/protocol); pytgcalls feeds them to
        ntgcalls and never shows them. Knowing the relay is what turns "it
        stutters" into a path that can be probed and compared. Only the
        address part is logged — ufrag/pwd/fingerprints stay private."""
        app = getattr(client, "_app", None)
        original = getattr(app, "join_group_call", None)
        if app is None or original is None:
            return

        async def _join(chat_id, *args, **kwargs):
            params = await original(chat_id, *args, **kwargs)
            try:
                logger.info("vc transport %s: %s", chat_id, _describe_transport(params))
            except Exception as ex:  # a log line must never break a join
                logger.debug("vc transport %s: not parsed (%s)", chat_id, ex)
            return params

        try:
            app.join_group_call = _join
        except Exception as ex:
            logger.warning("transport logging not installed: %s", ex)

    @staticmethod
    def _log_connection_changes(client: PyTgCalls) -> None:
        """Put every voice-chat connection state change in the log.

        pytgcalls swallows them after the join (a TIMEOUT/FAILED on a live
        group call just clears its cache, silently). A mid-song reconnect
        pauses ntgcalls' readers and re-syncs their clock — that IS a
        "stuck" moment for listeners, so it has to be visible next to the
        pulse lines. Wraps the binding callback pytgcalls installed; the
        original handler still runs unchanged."""
        binding = getattr(client, "_binding", None)
        original = getattr(client, "_handle_connection_changed", None)
        loop = getattr(client, "loop", None)
        if binding is None or original is None or loop is None:
            return

        def _on_change(chat_id, info):  # called from an ntgcalls thread
            state = getattr(getattr(info, "state", info), "name", str(info))
            log = logger.info if state in ("CONNECTING", "CONNECTED") else logger.warning
            log("vc connection %s: %s", chat_id, state)
            asyncio.run_coroutine_threadsafe(original(chat_id, info), loop)

        try:
            binding.on_connection_change(_on_change)
        except Exception as ex:
            logger.warning("connection-change logging not installed: %s", ex)

    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            await self.add_client(ub)
        logger.info("PyTgCalls client(s) started.")
