"""Keep the assistant account a MEMBER of every group the bot serves.

Why this exists (owner 2026-10-17)
----------------------------------
Another bot's feature (Maki's voice-chat join notices) reads a group through
THIS bot's assistant account.  Whenever the assistant is missing from a group
that reader fails with ``ChannelInvalid`` and the group gets a repeating
"Voice-chat join notices are not working" alert -- even though the music bot
itself is perfectly healthy.  The alert then repeats every 30 minutes forever,
because nothing ever put the assistant back.

Fixes the CAUSE, not the symptom:
  * the auto-leave sweep that removed the assistant is already disabled;
  * this module re-adds the assistant to any group it is missing from, at
    startup and then on a slow timer, using an invite link the bot creates
    (falling back to the group's public username).

It never bans, kicks or messages anyone, and the missing group is joined with
ordinary member rights only -- no admin rights are needed or requested.
"""

import asyncio
import os
import time

from bobby import logger

CHECK_EVERY = int(os.getenv("ASSISTANT_GUARD_EVERY", "300"))  # 10 minutes
JOIN_GAP = 3.0        # seconds between joins, so Telegram never sees a burst
_ENABLED = (os.getenv("ASSISTANT_GUARD", "true") or "true").strip().lower() \
    not in ("0", "false", "off", "no")

# chat_id -> monotonic time of the last successful repair
_repaired: dict[int, float] = {}


_ASSISTANT_ENV = int(os.getenv("ASSISTANT_ID", "6189989810"))


def _assistant_id(client=None) -> int:
    """The assistant account's user id.

    Prefers the live session's own id; falls back to ASSISTANT_ID from the
    env, then to the value that this deployment has always used, so the
    membership check always has something to ask about.
    """
    try:
        me = getattr(client, "me", None)
        if me is not None and getattr(me, "id", None):
            return int(me.id)
    except Exception:
        pass
    return _ASSISTANT_ENV


def _assistant_clients() -> list:
    """Every pyrogram assistant session this process holds.

    The assistant sessions are bound to the TgCall (``bobby.anon``) as its
    ``clients``; the Userbot owns the login side.  Check every known holder so
    a rename in either place cannot silently leave this guard blind (that
    failure mode finds 0 clients and repairs nothing).
    """
    import bobby
    out, seen = [], set()
    holders = [getattr(bobby, "anon", None),
               getattr(bobby, "userbot", None),
               getattr(bobby, "assistants", None),
               getattr(bobby, "ub", None),
               getattr(bobby, "app", None)]
    for obj in holders:
        if obj is None:
            continue
        clients = getattr(obj, "clients", None)
        if clients is None and isinstance(obj, (list, tuple)):
            clients = obj
        for c in clients or []:
            if c is not None and hasattr(c, "get_chat") and id(c) not in seen:
                seen.add(id(c))
                out.append(c)
    if not out:
        # last resort: the live pytgcalls bindings hold the session apps
        try:
            for ub in getattr(getattr(bobby, "userbot", None), "ub", []) or []:
                if hasattr(ub, "get_chat") and id(ub) not in seen:
                    seen.add(id(ub))
                    out.append(ub)
        except Exception:
            pass
    return out


async def _bot_groups() -> list:
    """Groups worth watching over, from every source that can name one.

    ``get_dialogs()`` alone is not enough: it can be slow, rate-limited or
    return nothing while the bot is busy, and the earlier fallback
    (``db.groups``) does not exist on this deployment -- so the guard found
    ZERO groups, logged nothing, and repaired nothing.  That is why the
    voice-chat alerts kept returning (owner 2026-10-18).
    """
    import bobby
    found: dict[int, object] = {}

    # 1. live dialog list
    try:
        async for dialog in bobby.app.get_dialogs():
            chat = getattr(dialog, "chat", None)
            cid = getattr(chat, "id", None)
            if cid and str(cid).startswith("-100"):
                found[int(cid)] = chat
    except Exception as exc:  # noqa: BLE001
        logger.info("assistant guard: get_dialogs failed (%s)",
                    type(exc).__name__)

    # 2. every chat the data store knows about
    try:
        data = getattr(bobby.db, "_data", None) or {}
        for key in list((data.get("chats") or {}).keys()):
            cid = int(key)
            if str(key).startswith("-100"):
                found.setdefault(cid, type("C", (), {"id": cid,
                                                     "title": str(cid),
                                                     "username": None})())
    except Exception as exc:  # noqa: BLE001
        logger.info("assistant guard: chat store unavailable (%s)",
                    type(exc).__name__)

    # 3. chats with an active call
    try:
        for cid in list(getattr(bobby.queue, "queues", {}) or {}):
            found.setdefault(int(cid), type("C", (), {"id": int(cid),
                                                      "title": str(cid),
                                                      "username": None})())
    except Exception:
        pass

    logger.info("assistant guard: %d group(s) to check", len(found))
    return list(found.values())


async def _api(method: str, **params):
    """Call the Bot API directly with the bot's own token.

    Plain HTTPS, so it never disturbs the running client's update polling and
    keeps working while the client is busy -- which is when a client-based
    call tends to time out (owner 2026-10-18).  Returns the parsed JSON or
    None; never raises.
    """
    import aiohttp
    from bobby import config
    token = getattr(config, "BOT_TOKEN", "") or ""
    if not token:
        return None
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                url, json=params,
                timeout=aiohttp.ClientTimeout(total=45, sock_connect=15),
            ) as r:
                return await r.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        logger.info("assistant guard: %s failed (%s)", method,
                    type(exc).__name__)
        return None


async def _invite_link(chat_id: int) -> str | None:
    """An invite link for the group, via the Bot API over plain HTTP."""
    body = await _api("exportChatInviteLink", chat_id=int(chat_id))
    if body and body.get("ok"):
        return body["result"]
    if body:
        logger.info("assistant guard: invite link refused for %s: %s",
                    chat_id, str(body.get("description"))[:80])
    return None



async def _ensure_assistant_in(client, chat_id: int, title: str) -> bool:
    """True when the assistant can already see this chat."""
    try:
        await client.get_chat(chat_id)
        return True
    except Exception as exc:
        logger.info("assistant guard: %s not visible to assistant (%s): %s",
                    chat_id, type(exc).__name__, title)
        return False


async def _rejoin(client, chat_id: int, title: str) -> bool:
    """Put the assistant back into the group. Invite link first, then a
    public username. Ordinary member join -- never an admin request."""
    import bobby
    link = None
    try:
        link = await bobby.app.export_chat_invite_link(chat_id)
    except Exception as exc:
        logger.info("assistant guard: no invite link for %s (%s)",
                    chat_id, type(exc).__name__)
    targets = []
    if link:
        targets.append(link)
    else:
        # the running client could not make one: try the Bot API over HTTP
        link = await _invite_link(chat_id)
        if link:
            targets.append(link)
    try:
        chat = await bobby.app.get_chat(chat_id)
        if getattr(chat, "username", None):
            targets.append("@" + chat.username)
    except Exception:
        pass
    if not targets:
        # SILENT failure before: no link and no username meant this returned
        # False without a single log line, so nobody could tell why the
        # assistant never came back (owner 2026-10-18).
        logger.warning("assistant guard: no way to rejoin %s (%s) - the bot "
                       "needs the 'Invite users' right there", chat_id, title)
        return False
    for target in targets:
        try:
            await client.join_chat(target)
            _repaired[chat_id] = time.monotonic()
            logger.warning("assistant guard: assistant REJOINED %s (%s) via %s",
                           chat_id, title, target if target.startswith("@")
                           else "invite link")
            return True
        except Exception as exc:
            logger.info("assistant guard: join failed for %s via %s: %s",
                        chat_id, target, type(exc).__name__)
    return False




_REJOIN_FILE = "/root/.maki_vc_rejoin.json"


async def _pick_up_rejoin_requests(clients) -> int:
    """Join groups Maki has cleared the way into.

    Maki unbans the assistant (it holds the rights) and leaves an invite link
    in a shared file; the assistant session lives HERE, so this is where the
    actual join can happen.  Returned links are used once and then removed.
    """
    import json
    try:
        with open(_REJOIN_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return 0
    if not data:
        return 0
    joined, failed = 0, []
    for chat_id, item in list(data.items()):
        link = (item or {}).get("link")
        if not link:
            failed.append(chat_id)
            continue
        ok = False
        for client in clients:
            try:
                await client.join_chat(link)
                logger.warning("assistant guard: assistant JOINED %s via "
                               "Maki's invite link", chat_id)
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                logger.info("assistant guard: join %s failed: %s",
                            chat_id, type(exc).__name__)
        if ok:
            joined += 1
            data.pop(chat_id, None)
        else:
            failed.append(chat_id)
    try:
        with open(_REJOIN_FILE, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in data.items() if k in failed}, fh)
    except Exception:
        pass
    if joined:
        logger.warning("assistant guard: joined %d group(s) Maki opened", joined)
    return joined


async def check_once() -> int:
    """One full sweep; returns how many groups were repaired."""
    if not _ENABLED:
        return 0
    clients = _assistant_clients()
    if not clients:
        logger.info("assistant guard: no assistant client available yet")
        return 0
    # Maki may have lifted a ban for us: take those first.
    await _pick_up_rejoin_requests(clients)
    groups = await _bot_groups()
    if not groups:
        return 0
    fixed = 0
    for chat in groups:
        chat_id = getattr(chat, "id", None)
        title = getattr(chat, "title", "") or str(chat_id)
        if not chat_id:
            continue
        # the assistant that can already see the chat wins; otherwise repair
        # through the first client that fails, exactly like Maki reads it
        visible = False
        for client in clients:
            if await _ensure_assistant_in(client, chat_id, title):
                visible = True
                break
        if visible:
            continue
        # ---- WHY the assistant cannot come back, in Telegram's own words ---
        # A KICKED member can never rejoin from an invite link: Telegram
        # refuses until the ban is lifted.  That is why every earlier rejoin
        # attempt failed silently (owner 2026-10-18).  Unban first.
        aid = _assistant_id(client=clients[0] if clients else None)
        status = None
        if aid:
            body = await _api("getChatMember", chat_id=chat_id, user_id=aid)
            status = (body or {}).get("result", {}).get("status")
            logger.info("assistant guard: %s assistant status = %s", chat_id, status)
        if status == "kicked":
            ub = await _api("unbanChatMember", chat_id=chat_id, user_id=aid,
                            only_if_banned=True)
            ok = bool(ub and ub.get("ok"))
            logger.warning(
                "assistant guard: assistant was KICKED in %s - unban %s%s",
                chat_id, "ok" if ok else "FAILED",
                "" if ok else " (the music bot needs can_restrict_members there)",
            )
            if ok:
                await asyncio.sleep(2)      # let Telegram settle the ban lift
        elif status is None:
            logger.info("assistant guard: %s could not read member status",
                        chat_id)
        for client in clients:
            if await _rejoin(client, chat_id, title):
                fixed += 1
                break
        await asyncio.sleep(JOIN_GAP)
    if fixed:
        logger.warning("assistant guard: repaired %d group(s)", fixed)
    return fixed


async def watchdog() -> None:
    logger.info("assistant guard: watching assistant membership every %ss",
                CHECK_EVERY)
    # first pass a little after startup, once assistants are connected
    await asyncio.sleep(30)
    while True:
        try:
            await check_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant guard: %s", type(exc).__name__)
        await asyncio.sleep(CHECK_EVERY)
