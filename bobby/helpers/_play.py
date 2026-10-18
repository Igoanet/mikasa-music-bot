# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import asyncio
import re

from pyrogram import enums, errors, types

from bobby import app, config, db, logger, queue, yt
from bobby.helpers._selfdel import arm_delete, clean_reply
from bobby.helpers import utils


def play_query(m: types.Message) -> str:
    """Return the command payload from Telegram's original text/caption.

    ``Message.command`` is useful for flags but tokenises its input, losing
    the line breaks in a pasted lyric.  Keep that text intact until
    ``YouTube.search`` can normalise it for its provider request.
    """
    raw = getattr(m, "text", None) or getattr(m, "caption", None) or ""
    if not isinstance(raw, str):
        return ""
    payload = re.sub(r"^\s*/\S+(?:\s+|$)", "", raw, count=1)
    if len(m.command) > 1 and m.command[1] == "-f":
        payload = re.sub(r"^\s*-f(?:\s+|$)", "", payload, count=1)
    return payload.strip()


async def _meet_assistant(client) -> None:
    """Make sure the bot can resolve the assistant's peer.

    Telegram refuses to resolve a user id the bot has never contacted
    (PEER_ID_INVALID). Username lookup works without prior contact; as a
    last resort the assistant pings the bot so the incoming update
    registers the peer in the bot's storage.
    """
    try:
        await app.resolve_peer(client.id)
        return
    except errors.PeerIdInvalid:
        pass
    if client.username:
        try:
            await app.get_users(client.username)
            return
        except Exception:
            pass
    try:
        await client.send_message(app.username, "/start")
    except Exception as ex:
        logger.warning(f"assistant peer warm-up failed: {ex}")


def checkUB(play):
    async def wrapper(_, m: types.Message):
        if not m.from_user:
            return await clean_reply(m, m.lang["play_user_invalid"])

        chat_id = m.chat.id
        if m.chat.type != enums.ChatType.SUPERGROUP:
            await clean_reply(m, m.lang["play_chat_invalid"])
            return await app.leave_chat(chat_id)

        query = play_query(m)
        if not m.reply_to_message and not query:
            return await clean_reply(m, m.lang["play_usage"])

        if len(queue.get_queue(chat_id)) >= config.QUEUE_LIMIT:
            return await clean_reply(m, m.lang["play_queue_full"].format(config.QUEUE_LIMIT))

        force = m.command[0].endswith("force") or (
            # exact flag only — a substring check force-plays any query
            # starting with e.g. "lo-fi" (the flag is "/play -f <query>")
            len(m.command) > 1 and m.command[1] == "-f"
        )
        video = m.command[0][0] == "v" and config.VIDEO_PLAY
        url = utils.get_url(m)
        # Never let the strict "invalid" gate kill a link we can actually
        # play: id_regex understands every video-link shape (incl. app-share
        # links like watch?app=desktop&v=..., live/, embed/), so it is the
        # final word. The gate only rejects YouTube pages with no video id
        # (channel/feed/search pages) — and it logs, so a rejection is
        # never invisible again.
        if url and yt.invalid(url) and not yt.id_regex.search(url):
            logger.warning("play: rejected unplayable url=%r chat=%s", url, chat_id)
            return await clean_reply(m, m.lang["play_not_found"].format(config.SUPPORT_CHAT))
        m3u8 = url and not yt.valid(url)

        play_mode = await db.get_play_mode(chat_id)
        if getattr(m, "autoplay", False):
            # the group's own autoplay setting (admin-only to change) is the
            # authorisation here; the synthetic author is the bot itself, so
            # a membership check would be meaningless
            pass
        elif play_mode:
            # Admins-only playback is intentionally stricter than every other
            # playback/VC permission: ask Telegram for this user's current
            # membership and do not honour cached admins, auth, or sudo.
            from bobby.helpers._admins import is_live_group_admin

            if not await is_live_group_admin(chat_id, m):
                return await clean_reply(m, m.lang["play_admin"])
        # Outside the strict group-owner policy, preserve the historical
        # force-play setting and its cached-admin/auth/sudo behaviour.
        elif force and not await db.get_force_mode(chat_id):
            adminlist = await db.get_admins(chat_id)
            if (
                m.from_user.id not in adminlist
                and not await db.is_auth(chat_id, m.from_user.id)
                and not m.from_user.id in app.sudoers
            ):
                return await clean_reply(m, m.lang["play_admin"])

        if chat_id not in db.active_calls:
            try:
                client = await db.get_client(chat_id)
            except RuntimeError:
                return await clean_reply(m, 
                    m.lang.get(
                        "play_no_assistant",
                        "⚠️ <b>No Assistant Available</b>\n\nNo assistant "
                        "accounts are connected yet. The bot owner must add "
                        "one first (private chat with the bot → /accounts).",
                    )
                )
            await _meet_assistant(client)
            try:
                member = await app.get_chat_member(chat_id, client.id)
                if member.status in [
                    enums.ChatMemberStatus.BANNED,
                    enums.ChatMemberStatus.RESTRICTED,
                ]:
                    try:
                        await app.unban_chat_member(
                            chat_id=chat_id, user_id=client.id
                        )
                    except Exception:
                        return await clean_reply(m, 
                            m.lang["play_banned"].format(
                                app.name,
                                client.id,
                                client.mention,
                                f"@{client.username}" if client.username else None,
                            )
                        )
            except errors.ChatAdminRequired:
                return await clean_reply(m, m.lang["admin_required"])
            except errors.PeerIdInvalid:
                return await clean_reply(m, 
                    m.lang.get(
                        "play_assistant_lost",
                        "⚠️ <b>Assistant Unreachable</b>\n\nI can't reach the "
                        "assistant account right now. The bot owner should "
                        "remove it in /accounts and add it again.",
                    )
                )
            except errors.UserNotParticipant:
                if m.chat.username:
                    invite_link = m.chat.username
                else:
                    try:
                        invite_link = (await app.get_chat(chat_id)).invite_link
                        if not invite_link:
                            invite_link = await app.export_chat_invite_link(chat_id)
                    except errors.ChatAdminRequired:
                        return await clean_reply(m, m.lang["admin_required"])
                    except Exception as ex:
                        return await clean_reply(m, 
                            m.lang["play_invite_error"].format(type(ex).__name__)
                        )

                umm = await clean_reply(m, m.lang["play_invite"].format(app.name),
                            preserve=True)
                await asyncio.sleep(2)
                try:
                    await client.join_chat(invite_link)
                except errors.UserAlreadyParticipant:
                    pass
                except errors.InviteRequestSent:
                    await asyncio.sleep(2)
                    try:
                        await app.approve_chat_join_request(chat_id, client.id)
                    except errors.HideRequesterMissing:
                        pass
                    except Exception as ex:
                        await umm.edit_text(
                            m.lang["play_invite_error"].format(type(ex).__name__)
                        )
                        arm_delete(umm)
                        return umm
                except Exception as ex:
                    logger.error(f"Error joining chat - {chat_id}: {ex}")
                    await umm.edit_text(
                        m.lang["play_invite_error"].format(type(ex).__name__)
                    )
                    arm_delete(umm)
                    return umm

                await umm.delete()

        if await db.get_cmd_delete(chat_id):
            try:
                await m.delete()
            except Exception:
                pass

        return await play(_, m, force, m3u8, video, url, query)

    return wrapper
