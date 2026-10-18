"""Owner's global user restriction: a restricted user can't use any bot function.

The list is shared with the group-help bot (bobby/core/restrictions.py is a symlink to
bots/shared/restrictions.py), so `/restrict` here also applies there. bobby/__main__.py hooks
the dispatcher before any plugin loads (see bobby/core/restrict_gate.py), so every handler of
this bot is hidden from restricted users; service events such as "video chat ended" still work.
The small handlers below only tell the restricted user in PM / on a button tap.

    /restrict <reply|@user|id>     /unrestrict <reply|@user|id>     /restricted
"""

import html
import time

from pyrogram import StopPropagation, enums, filters, types

from bobby import app, config, logger
from bobby.core import restrict_gate, restrictions

NOTICE = "❌ You're restricted from using this bot."
_NOTICE_EVERY = 300  # seconds between notices to the same user in PM
_last_notice: dict[int, float] = {}


_blocked = restrict_gate.blocked_by(config.OWNER_ID)


@app.on_message(filters.private & filters.regex(r"^/"), group=-10)
@restrict_gate.exempt
async def _pm_notice(_, m: types.Message):
    """Restricted users get one short answer in PM; in groups the bot stays silent."""
    if not _blocked(m.from_user):
        return
    now = time.monotonic()
    if now - _last_notice.get(m.from_user.id, 0.0) > _NOTICE_EVERY:
        _last_notice[m.from_user.id] = now
        try:
            await m.reply_text(NOTICE)
        except Exception:
            pass


@app.on_callback_query(group=-10)
@restrict_gate.exempt
async def _gate_callback(_, cq: types.CallbackQuery):
    if not _blocked(cq.from_user):
        return
    try:
        await cq.answer(NOTICE, show_alert=True)
    except Exception:
        pass
    raise StopPropagation


@app.on_inline_query(group=-10)
@restrict_gate.exempt
async def _gate_inline(_, iq: types.InlineQuery):
    if not _blocked(iq.from_user):
        return
    try:
        await iq.answer([], cache_time=5, is_personal=True)
    except Exception:
        pass
    raise StopPropagation


async def _target(m: types.Message) -> types.User | None:
    """Reply → that sender; else the first argument as @username / id / mention-picker tag."""
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user
    for ent in m.entities or []:
        if ent.type == enums.MessageEntityType.TEXT_MENTION and ent.user:
            return ent.user
    if len(m.command) < 2:
        return None
    arg = m.command[1].lstrip("@")
    try:
        user = await app.get_users(int(arg) if arg.isdigit() else arg)
    except Exception:
        return None
    return None if isinstance(user, list) else user  # a single ident never yields a list


def _label(user: types.User) -> str:
    name = html.escape(user.first_name or user.username or str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a> (<code>{user.id}</code>)'


@app.on_message(filters.command(["restrict", "unrestrict", "restricted"]) & filters.user(app.owner))
async def _restrict_cmd(_, m: types.Message):
    cmd = m.command[0].lower()
    if cmd == "restricted":
        users = restrictions.restricted()
        if not users:
            return await m.reply_text("ℹ️ Nobody is restricted.")
        lines = []
        for uid, rec in users.items():
            name = html.escape(rec.get("name") or "")
            when = time.strftime("%d %b %Y", time.localtime(rec.get("at", 0))) if rec.get("at") else ""
            lines.append(f"• <code>{uid}</code> {name} {('— ' + when) if when else ''}".rstrip())
        return await m.reply_text(
            "🚫 <b>Restricted users</b> (both bots):\n" + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML)

    user = await _target(m)
    if user is None:
        return await m.reply_text(
            f"⚠️ Usage: reply to the person with <code>/{cmd}</code>, or "
            f"<code>/{cmd} @username</code> / <code>/{cmd} user_id</code>.",
            parse_mode=enums.ParseMode.HTML)
    if user.id == config.OWNER_ID:
        return await m.reply_text("⚠️ You can't restrict yourself.")
    if user.is_self:
        return await m.reply_text("⚠️ That's me.")

    if cmd == "restrict":
        added = restrictions.restrict(user.id, by=m.from_user.id, name=user.first_name or user.username or "")
        logger.info("restrict: %s restricted by owner (%s)", user.id, "new" if added else "already")
        text = (f"🚫 {_label(user)} can no longer use the music bot or the group-help bot."
                if added else f"ℹ️ {_label(user)} is already restricted.")
    else:
        removed = restrictions.unrestrict(user.id)
        logger.info("restrict: %s unrestricted by owner (%s)", user.id, "removed" if removed else "not listed")
        text = (f"✅ {_label(user)} can use both bots again."
                if removed else f"ℹ️ {_label(user)} wasn't restricted.")
    await m.reply_text(text, parse_mode=enums.ParseMode.HTML)
