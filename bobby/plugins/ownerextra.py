"""Extra Owner-Panel sections — every important function as a button.

Kept in its own module so the existing owner.py panel is only touched where
its keyboard is built.  Every section is defensive: a missing dependency
degrades to a helpful message instead of an error.
"""
import html
import os
import shutil
import time

from pyrogram import enums, filters, types

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
    await cq.answer("Measuring…")
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
    await cq.answer("Cleaning…")
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
    await cq.answer("Checking…")
    lines = []
    found = False
    for modname in ("bobby.core.calls", "bobby.core.bot"):
        try:
            mod = __import__(modname, fromlist=["*"])
            calls = getattr(mod, "calls", None) or getattr(mod, "bot", None)
            registry = getattr(calls, "active", None) or getattr(calls, "_active", None)
            if registry is not None:
                lines = [f"• <code>{c}</code>" for c in list(registry)[:25]]
                found = True
                break
        except Exception:
            continue
    if found:
        body = "\n".join(lines) if lines else "No active streams."
    else:
        body = (f"Groups served: <b>{len(await db.get_chats())}</b>\n\n"
                "<i>Use /active for the live stream list.</i>")
    await cq.message.edit_text(f"<b>📡 Active streams</b>\n\n{body}", reply_markup=_back())


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
    await cq.answer("Counting…")
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
_GCN = "ogc"          # callback prefix, kept short for the 64-byte limit


def _gc_list_kb(chat_ids):
    rows, row = [], []
    for cid in chat_ids:
        title = _chat_title_cache.get(cid) or str(cid)
        row.append(_ikb(("💬 " + title)[:28], "%s:open:%s" % (_GCN, cid)))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    if not rows:
        rows = [[_ikb("No groups found", "%s:list" % _GCN)]]
    rows.append([_ikb("« Back", "own_back", enums.ButtonStyle.PRIMARY)])
    return _ikm(rows)


_chat_title_cache: dict = {}


def _gc_group_kb(cid):
    B = enums.ButtonStyle
    return _ikm([
        [_ikb("📋 Rights", "%s:rights:%s" % (_GCN, cid)),
         _ikb("🔗 Invite link", "%s:link:%s" % (_GCN, cid))],
        [_ikb("🚫 Banned list", "%s:bans:%s" % (_GCN, cid)),
         _ikb("🔓 Unban someone", "%s:bans:%s" % (_GCN, cid))],
        [_ikb("⚠️ Mass-ban (silent)", "%s:mbsure:%s" % (_GCN, cid), B.DANGER)],
        [_ikb("🔄 Rescan groups", "%s:list" % _GCN),
         _ikb("« Back", "%s:list" % _GCN)],
    ])


async def _gc_group_ids():
    """Every group the assistant knows, cached titles included."""
    try:
        import bobby.plugins.owner as _ow
        ids = await _ow._assistant_group_ids()
    except Exception:
        ids = []
    if not ids:
        try:
            ids = [int(c) for c in (await db.get_chats() or []) if int(c) < 0]
        except Exception:
            ids = []
    for cid in ids:
        if cid in _chat_title_cache:
            continue
        try:
            _chat_title_cache[cid] = (await app.get_chat(cid)).title or str(cid)
        except Exception:
            _chat_title_cache[cid] = str(cid)
    return sorted(set(ids), key=lambda c: _chat_title_cache.get(c, str(c)).lower())


@app.on_callback_query(filters.regex(r"^ogc:list$") & filters.user(config.OWNER_ID))
async def ogc_list(_, cq: types.CallbackQuery):
    await cq.answer("Scanning groups…")
    ids = await _gc_group_ids()
    await cq.message.edit_text(
        "<b>🛠 Group console</b>\n\n"
        f"<b>{len(ids)}</b> groups — tap one to manage it.\n"
        "<i>Every action runs silently: nothing is posted to the group.</i>",
        reply_markup=_gc_list_kb(ids))


@app.on_callback_query(filters.regex(r"^ogc:open:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_open(_, cq: types.CallbackQuery):
    await cq.answer()
    cid = int(cq.data.rsplit(":", 1)[-1])
    title = _chat_title_cache.get(cid) or str(cid)
    try:
        chat = await app.get_chat(cid)
        title = chat.title or title
        members = getattr(chat, "members_count", None)
    except Exception:
        members = None
    await cq.message.edit_text(
        f"<b>🛠 {html.escape(str(title))}</b>\n"
        f"<code>{cid}</code>"
        + (f" · <b>{members:,}</b> members" if members else "")
        + "\n\nPick an action.",
        reply_markup=_gc_group_kb(cid))


@app.on_callback_query(filters.regex(r"^ogc:rights:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_rights(_, cq: types.CallbackQuery):
    await cq.answer("Checking…")
    cid = int(cq.data.rsplit(":", 1)[-1])
    RIGHTS = [("can_manage_video_chats", "Video chats"),
              ("can_delete_messages", "Delete msgs"),
              ("can_restrict_members", "Ban users"),
              ("can_invite_users", "Invite users"),
              ("can_pin_messages", "Pin msgs"),
              ("can_change_info", "Change info"),
              ("can_promote_members", "Promote"),
              ("can_manage_chat", "Manage chat")]
    try:
        me = await app.get_me()
        mem = await app.get_chat_member(cid, me.id)
        st = getattr(mem.status, "value", str(mem.status))
        priv = getattr(mem, "privileges", None)
    except Exception as ex:
        return await cq.message.edit_text(
            f"⚠️ Cannot read rights: <code>{type(ex).__name__}</code>",
            reply_markup=_gc_group_kb(cid))
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
    await cq.answer("Getting link…")
    cid = int(cq.data.rsplit(":", 1)[-1])
    try:
        link = await app.export_chat_invite_link(cid)
    except Exception as ex:
        return await cq.message.edit_text(
            f"⚠️ No link: <code>{type(ex).__name__}</code> — "
            "the bot needs <b>Invite users</b> in that group.",
            reply_markup=_gc_group_kb(cid))
    await cq.message.edit_text(
        f"<b>🔗 Invite link</b>\n"
        f"{html.escape(_chat_title_cache.get(cid, str(cid)))}\n"
        f"<code>{cid}</code>\n\n{html.escape(link)}",
        reply_markup=_gc_group_kb(cid))


@app.on_callback_query(filters.regex(r"^ogc:bans:(-?\d+)$") & filters.user(config.OWNER_ID))
async def ogc_bans(_, cq: types.CallbackQuery):
    await cq.answer("Fetching…")
    cid = int(cq.data.rsplit(":", 1)[-1])
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


@app.on_callback_query(filters.regex(r"^own_groupconsole$") & filters.user(config.OWNER_ID))
async def cb_own_groupconsole(_, cq: types.CallbackQuery):
    await cq.answer("Scanning groups…")
    ids = await _gc_group_ids()
    await cq.message.edit_text(
        "<b>\U0001f6e0 Group console</b>\n\n"
        f"<b>{len(ids)}</b> groups — tap one to manage it.\n"
        "<i>Every action runs silently: nothing is posted to the group.</i>",
        reply_markup=_gc_list_kb(ids))
