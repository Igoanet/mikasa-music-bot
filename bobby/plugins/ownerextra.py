"""Extra Owner-Panel sections — every important function as a button.

Kept in its own module so the existing owner.py panel is only touched where
its keyboard is built.  Every section is defensive: a missing dependency
degrades to a helpful message instead of an error.
"""
import html
import os
import shutil
import time

import asyncio
from pyrogram import enums, errors, filters, types

from bobby import app, config, db, logger


def _ikb(text, data, style=None, icon=None):
    from pyrogram.types import InlineKeyboardButton
    kw = {"callback_data": data}
    if style:
        kw["style"] = style
    if icon:
        kw["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(text, **kw)


def _ikm(rows):
    from pyrogram.types import InlineKeyboardMarkup
    return InlineKeyboardMarkup(rows)


def _back():
    return _ikm([[_ikb("« Back", "own_back", enums.ButtonStyle.PRIMARY)]])


def _owner_only(cq) -> bool:
    return bool(cq.from_user and cq.from_user.id == config.OWNER_ID)


def _dir_mb(path) -> float:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except Exception:
        pass
    return total / (1024 * 1024)


# ── 🧹 Storage & clean ──────────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_clean$") & filters.user(config.OWNER_ID))
async def cb_own_clean(_, cq: types.CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>🧹 Storage</b>\n\n<i>Measuring storage usage...</i>", reply_markup=_back())
    except Exception:
        pass
    # dirs are relative to the bot's working directory (see core/dir.py)
    rows = [("Downloads", "downloads"), ("Cache", "cache"),
            ("Scratch (/tmp)", "/tmp")]
    lines = ["<b>🧹 Storage</b>", ""]
    for label, path in rows:
        lines.append(f"• {label}: <b>{_dir_mb(path):.1f} MB</b>")
    try:
        usage = shutil.disk_usage("/")
        lines.append(f"\nDisk: <b>{usage.used/1e9:.1f}/{usage.total/1e9:.1f} GB</b> "
                     f"({usage.used*100//usage.total}%)")
    except Exception:
        pass
    lines.append("\n<i>Use /clean to wipe downloads and cache.</i>")
    await cq.message.edit_text("\n".join(lines),
                               reply_markup=_ikm([
                                   [_ikb("🧹 Clean now", "own_clean_go",
                                         enums.ButtonStyle.DANGER)],
                                   [_ikb("« Back", "own_back", enums.ButtonStyle.PRIMARY)],
                               ]))


@app.on_callback_query(filters.regex(r"^own_clean_go$") & filters.user(config.OWNER_ID))
async def cb_own_clean_go(_, cq: types.CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>🧹 Storage</b>\n\n<i>Cleaning downloads and cache...</i>", reply_markup=_back())
    except Exception:
        pass
    freed = 0.0
    for path in ("downloads", "cache"):
        before = _dir_mb(path)
        try:
            for entry in os.listdir(path):
                target = os.path.join(path, entry)
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        os.remove(target)
                except OSError:
                    pass
        except Exception:
            pass
        freed += max(0.0, before - _dir_mb(path))
    await cq.message.edit_text(f"<b>✅ Cleaned</b> — freed <b>{freed:.1f} MB</b>.",
                               reply_markup=_back())


# ── 📡 Active streams ───────────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_vc$") & filters.user(config.OWNER_ID))
async def cb_own_vc(_, cq: types.CallbackQuery):
    from bobby import queue
    await cq.answer()
    active = list(getattr(db, "active_calls", []))
    lines = []
    for cid in active[:25]:
        playing = queue.get_current(cid)
        t = playing.title[:25] if playing else "Active Stream"
        lines.append(f"• <code>{cid}</code> — <b>{html.escape(t)}</b>")
    body = "\n".join(lines) if lines else "No active streams currently."
    await cq.message.edit_text(
        f"<b>📡 Active streams ({len(active)})</b>\n\n{body}",
        reply_markup=_back()
    )


# ── 🔒 Play mode ────────────────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_playmode$") & filters.user(config.OWNER_ID))
async def cb_own_playmode(_, cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "<b>🔒 Play mode</b>\n\n"
        "Controls who may start playback in a group.  Change it in the group "
        "itself — the setting is per chat:\n\n"
        "<code>/playmode admins</code> — only admins may play\n"
        "<code>/playmode everyone</code> — anyone may play\n\n"
        "<i>Autoplay is separate: <code>/autoplay on|off</code> in the group.</i>",
        reply_markup=_back())


# ── 🚫 Blacklist ────────────────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_blacklist$") & filters.user(config.OWNER_ID))
async def cb_own_blacklist(_, cq: types.CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>🚫 Blacklist</b>\n\n<i>Loading blacklist...</i>", reply_markup=_back())
    except Exception:
        pass
    try:
        chats = len(db.blacklisted)
    except Exception:
        chats = "?"
    try:
        users = len(app.bl_users)
    except Exception:
        users = "?"
    await cq.message.edit_text(
        f"<b>🚫 Blacklist</b>\n\n"
        f"Blocked groups: <b>{chats}</b>\n"
        f"Blocked users: <b>{users}</b>\n\n"
        "<code>/blacklist</code> — block a chat or user (reply or pass an id)\n"
        "<code>/unblacklist</code> — lift it\n"
        "<code>/bans</code> — banned users in a group",
        reply_markup=_back())


# ── 📄 Log channel ──────────────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_logbind$") & filters.user(config.OWNER_ID))
async def cb_own_logbind(_, cq: types.CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>📄 Log channel</b>\n\n<i>Loading log channel configuration...</i>", reply_markup=_back())
    except Exception:
        pass
    cid = 0
    try:
        cid = int(await db.get("log_channel") or 0)
    except Exception:
        pass
    if not cid:
        cid = int(getattr(config, "LOGGER_ID", 0) or 0)
    title = f"<code>{cid}</code>" if cid else "<i>not set</i>"
    if cid:
        try:
            chat = await app.get_chat(cid)
            title = f"<b>{html.escape(chat.title or str(cid))}</b> (<code>{cid}</code>)"
        except Exception:
            pass
    await cq.message.edit_text(
        f"<b>📄 Log channel</b>\n\nCurrent: {title}\n\n"
        "<b>To bind one:</b>\n"
        "1. Add me to the channel as admin\n"
        "2. Forward any message from it to my DM\n"
        "3. Reply <code>/setlog</code> to that forward\n\n"
        "<i>Group joins/leaves and playback events are posted there.</i>",
        reply_markup=_ikm([
            [_ikb("🔔 Send a test", "own_logtest", enums.ButtonStyle.PRIMARY)],
            [_ikb("« Back", "own_back", enums.ButtonStyle.PRIMARY)],
        ]))


@app.on_callback_query(filters.regex(r"^own_logtest$") & filters.user(config.OWNER_ID))
async def cb_own_logtest(_, cq: types.CallbackQuery):
    try:
        from bobby.plugins.logsetup import to_log
        ok = await to_log("🔔 Test message from the owner panel.")
    except Exception:
        ok = False
    await cq.answer("Sent ✅" if ok else "Failed — check the bot's admin rights",
                    show_alert=True)


# ── 🛠 Maintenance: restart with confirmation ───────────────────────────────
@app.on_callback_query(filters.regex(r"^own_restart$") & filters.user(config.OWNER_ID))
async def cb_own_restart(_, cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "<b>🔄 Restart the bot?</b>\n\n"
        "The music bot will stop and come straight back (systemd restarts it). "
        "Any stream in progress ends.",
        reply_markup=_ikm([
            [_ikb("Yes, restart", "own_restart_yes", enums.ButtonStyle.DANGER)],
            [_ikb("Cancel", "own_back", enums.ButtonStyle.PRIMARY)],
        ]))


@app.on_callback_query(filters.regex(r"^own_restart_yes$") & filters.user(config.OWNER_ID))
async def cb_own_restart_yes(_, cq: types.CallbackQuery):
    await cq.answer("Restarting…", show_alert=True)
    try:
        await cq.message.edit_text("🔄 Restarting… back in a few seconds.")
    except Exception:
        pass
    logger.warning("owner panel: restart requested by %s", cq.from_user.id)
    os._exit(0)      # systemd Restart=always brings it back


# ── 📜 Commands reference ───────────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^own_cmds$") & filters.user(config.OWNER_ID))
async def cb_own_cmds(_, cq: types.CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "<b>📜 Commands</b>\n\n"
        "<b>Playback</b> (group)\n"
        "<code>/play /vplay /song /queue /skip /pause /resume /stop /seek /loop</code>\n"
        "<code>/shuffle /speed /autoplay /playmode /active</code>\n\n"
        "<b>Groups</b>\n"
        "<code>/lang /clean /help /ping /stats</code>\n\n"
        "<b>Owner only</b>\n"
        "<code>/owner /addsudo /delsudo /broadcast /blacklist /bans</code>\n"
        "<code>/setlog /unsetlog /logstatus /testlog /restart</code>\n"
        "<code>/refreshassistant</code>\n\n"
        "<b>Owner — group console</b>\n"
        "<i>Silent: replies in DM, nothing is posted to the group.</i>\n"
        "<code>/massban &lt;chat_id&gt;</code> — ban every non-admin member\n"
        "<code>/manage &lt;chat_id&gt;</code> — panel: rights, link, banned list\n"
        "<code>/chatlink &lt;chat_id&gt;</code> — invite link\n"
        "<code>/unban &lt;chat_id&gt; &lt;id&gt;</code> — lift one ban\n"
        "<code>/bans &lt;chat_id&gt;</code> — who is banned\n\n"
        "<b>All of the above are owner-only.</b>",
        reply_markup=_back())


# ── 🛠 Group console (button-driven) ────────────────────────────────────────
_GCN = "ogc"

_chat_link_cache: dict[int, tuple[str, str]] = {}
_chat_title_cache: dict[int, str] = {}
_admin_groups_cache: list[int] = []
_admin_groups_cache_ts: float = 0.0


async def _resolve_invite_link(cid: int) -> tuple[str | None, str | None]:
    """Resolve an invite link via Bot or Assistant fast and reliably without hanging."""
    from bobby import userbot

    # 0. Check link cache
    if cid in _chat_link_cache:
        return _chat_link_cache[cid]

    # 1. Fast Bot get_chat (already contains username or existing invite_link)
    try:
        c = await asyncio.wait_for(app.get_chat(cid), timeout=1.8)
        if getattr(c, "username", None):
            res = (f"https://t.me/{c.username}", "Public Username")
            _chat_link_cache[cid] = res
            return res
        if getattr(c, "invite_link", None):
            res = (c.invite_link, "Primary Link")
            _chat_link_cache[cid] = res
            return res
    except Exception:
        pass

    # 2. Bot export_chat_invite_link with strict timeout
    try:
        link = await asyncio.wait_for(app.export_chat_invite_link(cid), timeout=2.0)
        if link:
            res = (link, "Exported via Bot")
            _chat_link_cache[cid] = res
            return res
    except Exception:
        pass

    # 3. Assistant get_chat / export with strict timeout
    if getattr(userbot, "clients", None):
        for ub in userbot.clients:
            try:
                c = await asyncio.wait_for(ub.get_chat(cid), timeout=1.8)
                if getattr(c, "username", None):
                    res = (f"https://t.me/{c.username}", "Public Username")
                    _chat_link_cache[cid] = res
                    return res
                if getattr(c, "invite_link", None):
                    res = (c.invite_link, "Primary Link")
                    _chat_link_cache[cid] = res
                    return res
                link = await asyncio.wait_for(ub.export_chat_invite_link(cid), timeout=2.0)
                if link:
                    res = (link, "Exported via Assistant")
                    _chat_link_cache[cid] = res
                    return res
            except Exception:
                pass

    return None, None


def _gc_list_kb(chat_ids):
    rows, row = [], []
    for cid in chat_ids:
        title = _chat_title_cache.get(cid) or str(cid)
        row.append(_ikb(("💬 " + title)[:28], "%s:open:%s" % (_GCN, cid)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if not rows:
        rows = [[_ikb("No admin groups found", "%s:list:refresh" % _GCN)]]
    rows.append([_ikb("« Back", "own_back", enums.ButtonStyle.PRIMARY)])
    return _ikm(rows)


def _gc_group_kb(cid):
    B = enums.ButtonStyle
    return _ikm([
        [_ikb("📋 Rights", "%s:rights:%s" % (_GCN, cid)),
         _ikb("🔗 Invite link", "%s:link:%s" % (_GCN, cid))],
        [_ikb("🚫 Banned list", "%s:bans:%s" % (_GCN, cid)),
         _ikb("⚠️ Mass-ban (silent)", "%s:mbsure:%s" % (_GCN, cid), B.DANGER)],
        [_ikb("🔄 Rescan groups", "%s:list:refresh" % _GCN),
         _ikb("« Back", "%s:list" % _GCN)],
    ])


async def _gc_group_ids(force_refresh: bool = False) -> list[int]:
    """Every group where the bot is currently an administrator (cached for 30s)."""
    global _admin_groups_cache, _admin_groups_cache_ts
    now = time.monotonic()
    if not force_refresh and _admin_groups_cache and (now - _admin_groups_cache_ts < 30.0):
        return _admin_groups_cache

    candidate_ids = set()
    try:
        candidate_ids.update([int(c) for c in (await db.get_chats() or []) if int(c) < 0])
    except Exception:
        pass
    try:
        import bobby.plugins.owner as _ow
        candidate_ids.update(await _ow._assistant_group_ids())
    except Exception:
        pass

    async def _check_admin(cid: int):
        try:
            m = await asyncio.wait_for(app.get_chat_member(cid, "me"), timeout=1.8)
            if m.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                if cid not in _chat_title_cache or str(_chat_title_cache[cid]).startswith("-100"):
                    try:
                        chat = await asyncio.wait_for(app.get_chat(cid), timeout=1.5)
                        _chat_title_cache[cid] = chat.title or str(cid)
                    except Exception:
                        _chat_title_cache[cid] = str(cid)
                return cid
        except errors.FloodWait as fw:
            await asyncio.sleep(min(fw.value, 3))
            try:
                m = await asyncio.wait_for(app.get_chat_member(cid, "me"), timeout=1.8)
                if m.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    return cid
            except Exception:
                pass
        except Exception:
            pass
        return None

    if candidate_ids:
        results = await asyncio.gather(*[_check_admin(cid) for cid in candidate_ids])
        admin_ids = [cid for cid in results if cid is not None]
    else:
        admin_ids = []

    res = sorted(admin_ids, key=lambda c: _chat_title_cache.get(c, str(c)).lower())
    _admin_groups_cache = res
    _admin_groups_cache_ts = now
    return res


@app.on_callback_query(filters.regex(r"^ogc:list(:refresh)?$") & filters.user(config.OWNER_ID))
async def ogc_list(_, cq: types.CallbackQuery):
    await cq.answer()
    refresh = ":refresh" in (cq.data or "")
    if refresh:
        try:
            await cq.message.edit_text("<b>🛠 Group console</b>\n\n<i>Scanning admin groups, please wait...</i>", reply_markup=_back())
        except Exception:
            pass
    ids = await _gc_group_ids(force_refresh=refresh)
    await cq.message.edit_text(
        "<b>🛠 Group console</b>\n\n"
        f"<b>{len(ids)}</b> admin group{'s' if len(ids) != 1 else ''} — tap one to manage it.\n"
        "<i>Showing only groups where the bot is an administrator.</i>",
        reply_markup=_gc_list_kb(ids))

@app.on_callback_query(filters.regex(r"^ogc:open:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_open(_, cq: types.CallbackQuery):
    from bobby import userbot
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        await cq.message.edit_text("<b>🛠 Group console</b>\n\n<i>Loading group details...</i>", reply_markup=_ikm([[_ikb("« Back", "ogc:list", enums.ButtonStyle.PRIMARY)]]))
    except Exception:
        pass
    title = _chat_title_cache.get(cid) or str(cid)
    members = None
    try:
        chat = await app.get_chat(cid)
        title = chat.title or title
        members = getattr(chat, "members_count", None)
    except Exception:
        if getattr(userbot, "clients", None):
            for ub in userbot.clients:
                try:
                    chat = await ub.get_chat(cid)
                    title = chat.title or title
                    members = getattr(chat, "members_count", None)
                    break
                except Exception:
                    pass
    _chat_title_cache[cid] = title

    kb_rows = _gc_group_kb(cid).inline_keyboard
    # Add option to delete inactive group if unreachable
    if not members and title == str(cid):
        kb_rows.insert(3, [_ikb("🗑 Remove Inactive Group", "%s:delchat:%s" % (_GCN, cid), enums.ButtonStyle.DANGER)])

    await cq.message.edit_text(
        f"<b>🛠 {html.escape(str(title))}</b>\n"
        f"<code>{cid}</code>"
        + (f" · <b>{members:,}</b> members" if members else "")
        + "\n\nPick an action.",
        reply_markup=_ikm(kb_rows))


@app.on_callback_query(filters.regex(r"^ogc:rights:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_rights(_, cq: types.CallbackQuery):
    from bobby import userbot
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        await cq.message.edit_text(f"<b>📋 Rights</b>\n<code>{cid}</code>\n\n<i>Checking administrator rights...</i>", reply_markup=_gc_group_kb(cid))
    except Exception:
        pass
    RIGHTS = [("can_manage_video_chats", "Video chats"),
              ("can_delete_messages", "Delete msgs"),
              ("can_restrict_members", "Ban users"),
              ("can_invite_users", "Invite users"),
              ("can_pin_messages", "Pin msgs"),
              ("can_change_info", "Change info"),
              ("can_promote_members", "Promote"),
              ("can_manage_chat", "Manage chat")]
    me = await app.get_me()
    mem, priv, st = None, None, None
    try:
        mem = await app.get_chat_member(cid, me.id)
        st = getattr(mem.status, "value", str(mem.status))
        priv = getattr(mem, "privileges", None)
    except Exception:
        pass

    # If bot is not in chat or ChannelInvalid, check assistant
    if not mem:
        ub_mem, ub_st = None, None
        if getattr(userbot, "clients", None):
            for ub in userbot.clients:
                try:
                    ub_mem = await ub.get_chat_member(cid, "me")
                    ub_st = getattr(ub_mem.status, "value", str(ub_mem.status))
                    break
                except Exception:
                    pass

        title = html.escape(_chat_title_cache.get(cid, str(cid)))
        if ub_mem:
            # Assistant is in group
            return await cq.message.edit_text(
                f"<b>📋 Rights in {title}</b>\n<code>{cid}</code>\n\n"
                f"⚠️ <b>Bot Status:</b> Not in this group\n"
                f"👤 <b>Assistant Status:</b> <b>{ub_st}</b>\n\n"
                "<i>The assistant is in the chat. You can add the bot using the button below.</i>",
                reply_markup=_ikm([
                    [_ikb("➕ Add Bot with Assistant", "%s:addbot:%s" % (_GCN, cid), enums.ButtonStyle.PRIMARY)],
                    [_ikb("« Back", "%s:open:%s" % (_GCN, cid), enums.ButtonStyle.PRIMARY)],
                ]))
        else:
            # Neither in group
            return await cq.message.edit_text(
                f"<b>📋 Rights in {title}</b>\n<code>{cid}</code>\n\n"
                "⚠️ <b>Inactive Chat:</b> Neither the bot nor assistant is present in this group.\n"
                "<i>The group was deleted or the bot and assistant were removed.</i>",
                reply_markup=_ikm([
                    [_ikb("🗑 Remove Inactive Group", "%s:delchat:%s" % (_GCN, cid), enums.ButtonStyle.DANGER)],
                    [_ikb("« Back", "%s:open:%s" % (_GCN, cid), enums.ButtonStyle.PRIMARY)],
                ]))

    have = [l for a, l in RIGHTS if priv and getattr(priv, a, False)]
    miss = [l for a, l in RIGHTS if not (priv and getattr(priv, a, False))]
    await cq.message.edit_text(
        f"<b>📋 Rights in {html.escape(_chat_title_cache.get(cid, str(cid)))}</b>\n"
        f"<code>{cid}</code> · status <b>{st}</b>\n\n"
        f"<b>{len(have)}/8</b>\n"
        f"✅ {', '.join(have) or '—'}\n"
        f"❌ {', '.join(miss) or 'none — full power'}"
        + ("" if "Ban users" in have else
           "\n\n⚠️ <b>Ban users</b> missing — mass-ban will fail here."),
        reply_markup=_gc_group_kb(cid))


@app.on_callback_query(filters.regex(r"^ogc:link:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_link(_, cq: types.CallbackQuery):
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        await cq.message.edit_text(f"<b>🔗 Invite link</b>\n<code>{cid}</code>\n\n<i>Exporting invite link...</i>", reply_markup=_gc_group_kb(cid))
    except Exception:
        pass

    link, method = await _resolve_invite_link(cid)
    title = html.escape(_chat_title_cache.get(cid, str(cid)))
    if link:
        await cq.message.edit_text(
            f"<b>🔗 Invite link</b>\n"
            f"{title}\n"
            f"<code>{cid}</code>\n\n"
            f"<b>Link:</b> <a href=\"{html.escape(link)}\">{html.escape(link)}</a>\n"
            f"<i>({html.escape(method)})</i>",
            reply_markup=_gc_group_kb(cid),
            disable_web_page_preview=True)
    else:
        await cq.message.edit_text(
            f"<b>🔗 Invite link</b>\n"
            f"{title}\n"
            f"<code>{cid}</code>\n\n"
            "⚠️ <b>Cannot generate invite link.</b>\n\n"
            "Neither the bot nor assistant is present or has <b>Invite users</b> permissions in this chat.\n"
            "<i>If this group is no longer active, you can remove it from the list.</i>",
            reply_markup=_ikm([
                [_ikb("🗑 Remove Inactive Group", "%s:delchat:%s" % (_GCN, cid), enums.ButtonStyle.DANGER)],
                [_ikb("« Back", "%s:open:%s" % (_GCN, cid), enums.ButtonStyle.PRIMARY)],
            ]))


@app.on_callback_query(filters.regex(r"^ogc:bans:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_bans(_, cq: types.CallbackQuery):
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        await cq.message.edit_text(f"<b>🚫 Banned list</b>\n<code>{cid}</code>\n\n<i>Fetching banned members...</i>", reply_markup=_gc_group_kb(cid))
    except Exception:
        pass
    rows, n = [], 0
    try:
        async for mem in app.get_chat_members(
                cid, filter=enums.ChatMembersFilter.BANNED):
            if not mem.user:
                continue
            n += 1
            if len(rows) < 20:
                u = mem.user
                label = (u.first_name or str(u.id))[:22]
                rows.append([_ikb(f"🔓 {label}",
                                  "ogc:unban:%s:%s" % (cid, u.id))])
    except Exception as ex:
        return await cq.message.edit_text(
            f"⚠️ Cannot list bans: <code>{type(ex).__name__}</code>",
            reply_markup=_gc_group_kb(cid))
    if not rows:
        return await cq.message.edit_text(
            "<b>🚫 Banned list</b>\n\nNo banned users in that group.",
            reply_markup=_gc_group_kb(cid))
    rows.append([_ikb("« Back", "ogc:open:%s" % cid, enums.ButtonStyle.PRIMARY)])
    await cq.message.edit_text(
        f"<b>🚫 Banned in</b> {html.escape(_chat_title_cache.get(cid, str(cid)))}\n"
        f"<b>{n}</b> banned — tap one to unban"
        + (f"\n<i>(showing {len(rows)-1})</i>" if n > 20 else ""),
        reply_markup=_ikm(rows))


@app.on_callback_query(filters.regex(r"^ogc:unban:(-?\d+):(\d+)$") & filters.user(config.OWNER_ID))
async def ogc_unban(_, cq: types.CallbackQuery):
    _, _, cid_s, uid_s = cq.data.split(":")
    cid, uid = int(cid_s), int(uid_s)
    try:
        await app.unban_chat_member(cid, uid)
    except Exception as ex:
        return await cq.answer(f"Unban failed: {type(ex).__name__}", show_alert=True)
    await cq.answer("Unbanned.", show_alert=True)
    await ogc_bans(_, cq)


@app.on_callback_query(filters.regex(r"^ogc:mbsure:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_mbsure(_, cq: types.CallbackQuery):
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    await cq.message.edit_text(
        f"<b>⚠️ Mass-ban every member?</b>\n\n"
        f"{html.escape(_chat_title_cache.get(cid, str(cid)))}\n"
        f"<code>{cid}</code>\n\n"
        "<b>Silent</b> — runs in DM, nothing is posted to the group.\n"
        "Admins and the VC assistant are skipped.\n"
        "<b>This is permanent.</b>",
        reply_markup=_ikm([
            [_ikb("✔ Yes — ban everyone", "ogc:mbok:%s" % cid, enums.ButtonStyle.DANGER)],
            [_ikb("Cancel", "ogc:open:%s" % cid, enums.ButtonStyle.PRIMARY)],
        ]))


@app.on_callback_query(filters.regex(r"^ogc:mbok:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_mbok(_, cq: types.CallbackQuery):
    await cq.answer("Starting…")
    cid = int(cq.data.rsplit(":", 1)[-1])
    from bobby.plugins.owner_console import _run_massban

    await _run_massban(cq.from_user.id, cid, cq.message)



@app.on_callback_query(filters.regex(r"^ogc:delchat:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_delchat(_, cq: types.CallbackQuery):
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        await db.rm_chat(cid)
    except Exception:
        pass
    _chat_title_cache.pop(cid, None)
    await cq.message.edit_text(
        f"<b>🗑 Inactive Group Removed</b>\n\nGroup <code>{cid}</code> has been removed from the bot database.",
        reply_markup=_ikm([[_ikb("« Back to Groups", f"{_GCN}:list", enums.ButtonStyle.PRIMARY)]])
    )


@app.on_callback_query(filters.regex(r"^ogc:addbot:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_addbot(_, cq: types.CallbackQuery):
    await cq.answer("Adding bot…")
    cid = int(cq.data.rsplit(":", 1)[-1])
    success = False
    me = await app.get_me()
    from bobby import userbot
    if getattr(userbot, "clients", None):
        for ub in userbot.clients:
            try:
                await ub.add_chat_members(cid, me.id)
                success = True
                break
            except Exception as ex:
                logger.warning("Failed to add bot to %s via assistant: %s", cid, ex)
    if success:
        await cq.message.edit_text(
            f"<b>✅ Bot Added to Group!</b>\n\nBot successfully joined <code>{cid}</code> via Assistant.",
            reply_markup=_gc_group_kb(cid)
        )
    else:
        await cq.message.edit_text(
            f"<b>⚠️ Failed to Add Bot</b>\n\nAssistant does not have permissions to add members in <code>{cid}</code>.",
            reply_markup=_gc_group_kb(cid)
        )

@app.on_callback_query(filters.regex(r"^own_groupconsole$") & filters.user(config.OWNER_ID))
async def cb_own_groupconsole(_, cq: types.CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>🛠 Group console</b>\n\n<i>Scanning admin groups, please wait...</i>", reply_markup=_back())
    except Exception:
        pass
    ids = await _gc_group_ids()
    await cq.message.edit_text(
        "<b>\U0001f6e0 Group console</b>\n\n"
        f"<b>{len(ids)}</b> admin group{'s' if len(ids) != 1 else ''} — tap one to manage it.\n"
        "<i>Showing only groups where the bot is an administrator.</i>",
        reply_markup=_gc_list_kb(ids))
