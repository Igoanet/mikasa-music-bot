"""Live playback panel: a text progress bar plus disco button colours.

Row 1 of the panel is a progress line built here:
    MM:SS | ━━━━━🔘─────── | -MM:SS
It advances with the song (frozen while paused) and the panel's button
colours cycle at every tick (default 2s).  The panel is registered when it is
posted and released on any error or when the call ends.
"""

import asyncio
import copy
import logging
import os
import random
import time

from pyrogram import enums

logger = logging.getLogger("bobby")

ENABLED = True                       # always on -- there is no off switch
# Telegram rate-limits repeated edits of the SAME message.  At 2s the panel
# flooded (420 FLOOD_WAIT, 25-27s) and every such flood used to break the
# play flow.  5s of visual update is the safe floor; the tick also slows
# itself down further whenever Telegram complains (see add_penalty).
EVERY = max(3, int(os.getenv("DISCO_EVERY", "5")))
_SEGMENTS = 13
_PALETTE = (enums.ButtonStyle.PRIMARY, enums.ButtonStyle.SUCCESS,
            enums.ButtonStyle.DANGER)

_panels: dict[int, tuple[int, object]] = {}
_steps: dict[int, int] = {}
_pos: dict[int, dict] = {}
_PAUSED_UNTIL = 0.0
_penalty = 0.0          # extra seconds added to EVERY after a flood
_penalty_until = 0.0

def _clock(seconds) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return "00:00"
    return "%02d:%02d" % (total // 60, total % 60)


def progress_bar(elapsed, total) -> str:
    """`MM:SS | ━━━🔘──── | -MM:SS` -- no song name, exactly the panel line."""
    try:
        total = int(total or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        return "%s | %s | %s" % (_clock(elapsed), "━" * _SEGMENTS, "-00:00")
    elapsed = max(0, min(float(elapsed), float(total)))
    filled = int(round(_SEGMENTS * elapsed / total))
    filled = max(0, min(_SEGMENTS, filled))
    return "%s | %s\U0001f518%s | -%s" % (
        _clock(elapsed), "\u2501" * filled, "\u2500" * (_SEGMENTS - filled),
        _clock(total - elapsed),
    )


def add_penalty(seconds: float) -> None:
    """Telegram rate-limited an edit: slow the panel down for 15 minutes.

    Called by the playback path too, so a cosmetic message flood can never
    make the music itself look broken.
    """
    global _penalty, _penalty_until
    try:
        wait = float(seconds or 0)
    except (TypeError, ValueError):
        wait = 0.0
    _penalty = min(max(_penalty, wait), 120.0)
    _penalty_until = time.time() + 900


def register(chat_id: int, message_id: int, markup, total_sec=None) -> None:
    if not message_id or markup is None:
        return
    chat_id = int(chat_id)
    _panels[chat_id] = (int(message_id), markup)
    _pos[chat_id] = {
        "total": int(total_sec or 0), "elapsed": 0.0, "paused": False,
        "last": time.time(), "mid": int(message_id),
    }


def unregister(chat_id: int) -> None:
    chat_id = int(chat_id)
    _panels.pop(chat_id, None)
    _steps.pop(chat_id, None)
    _pos.pop(chat_id, None)


def _spans(row_len: int) -> list:
    """Where each button in a row sits horizontally.

    Telegram splits a row's width equally between its buttons, so a 2-button
    row and a 3-button row do NOT line up in columns.  Comparing by column
    index was wrong: it missed clashes between rows of different lengths.
    """
    return [(i / row_len, (i + 1) / row_len) for i in range(row_len)]


def _overlap(a, b) -> bool:
    """True when two buttons actually touch (share a vertical boundary)."""
    return a[0] < b[1] - 1e-9 and b[0] < a[1] - 1e-9


def _count_clashes(assign, spans) -> int:
    """How many touching button pairs share a colour."""
    n = 0
    for i, row in enumerate(assign):
        for j, col in enumerate(row):
            if j > 0 and row[j - 1] == col:
                n += 1                                   # same-row neighbour
            if i > 0:
                for k, other in enumerate(assign[i - 1]):
                    if other == col and _overlap(spans[i][j], spans[i - 1][k]):
                        n += 1                           # row above, touching
    return n


def _recolor(markup, step: int = 0):
    """Randomise the colours while keeping touching buttons distinct.

    Touching = same-row neighbours PLUS any button in the row above whose
    horizontal span overlaps.  Rows of different lengths do not line up in
    columns, so a full-width row touches every button beneath it.

    Telegram has only three button colours, and a 1-2-3-1 grid (progress,
    seek, controls, autoplay) cannot be coloured with zero clashes -- the
    full-width autoplay row sits under three different colours.  So the
    minimum is found exactly (a search over the whole panel) and one of the
    BEST colourings is chosen at random each tick: the single unavoidable
    clash is never worse than it must be, and it moves around instead of
    sticking to the same pair.
    """
    out = copy.deepcopy(markup)
    rows = getattr(out, "inline_keyboard", []) or []
    shape = [len(r) for r in rows]
    spans = [_spans(n) for n in shape]
    combos = 1
    for n in shape:
        combos *= 3 ** n
    if combos > 60000 or not shape:
        # too large to search exhaustively: keep the greedy pass
        above_spans: list = []
        for row in rows:
            sp = _spans(len(row))
            picked: list = []
            for i, btn in enumerate(row):
                banned = set()
                if i > 0:
                    banned.add(picked[i - 1][1])
                for s2, c2 in above_spans:
                    if _overlap(sp[i], s2):
                        banned.add(c2)
                allowed = [c for c in _PALETTE if c not in banned] or list(_PALETTE)
                pick = random.choice(allowed)
                picked.append((sp[i], pick))
                btn.style = pick
            above_spans = picked
        return out

    best, best_c = [], None
    for code in range(combos):
        x, assign = code, []
        for n in shape:
            row = []
            for _ in range(n):
                row.append(_PALETTE[x % len(_PALETTE)])
                x //= len(_PALETTE)
            assign.append(row)
        c = _count_clashes(assign, spans)
        if best_c is None or c < best_c:
            best_c, best = c, [assign]
        elif c == best_c:
            best.append(assign)
    chosen = random.choice(best)
    for row, cols in zip(rows, chosen):
        for btn, col in zip(row, cols):
            btn.style = col
    return out


async def _tick() -> None:
    global _PAUSED_UNTIL
    from bobby import app, db

    if time.time() < _PAUSED_UNTIL:
        return
    for chat_id, (mid, markup) in list(_panels.items()):
        try:
            if not await db.get_call(chat_id):
                unregister(chat_id)
                continue
            rows = getattr(markup, "inline_keyboard", None)
            if not rows:
                unregister(chat_id)
                continue
            st = _pos.get(chat_id)
            if st:
                now = time.time()
                playing = await db.playing(chat_id)
                if playing:
                    st["elapsed"] += now - st["last"]
                st["last"] = now
                st["paused"] = not playing
                if st["total"] and rows[0]:
                    bar = progress_bar(st["elapsed"], st["total"])
                    # the paused marker keeps the panel truthful, so a
                    # rebuild from the bar still shows Resume
                    rows[0][0].text = ("\u23f8 " + bar) if st["paused"] else bar
            step = _steps.get(chat_id, 0) + 1
            _steps[chat_id] = step
            await app.edit_message_reply_markup(
                chat_id=chat_id, message_id=mid, reply_markup=_recolor(markup, step),
            )
        except Exception as ex:  # noqa: BLE001
            name = type(ex).__name__
            if "Flood" in name or "Retry" in name:
                add_penalty(getattr(ex, "value", 5))
                _PAUSED_UNTIL = time.time() + float(getattr(ex, "value", 5) or 5)
                logger.info("disco: flood, backing off %ss (interval now %ss)",
                            int(_PAUSED_UNTIL - time.time()),
                            int(EVERY + _penalty))
                continue
            logger.info("disco %s: %s", chat_id, name)
            unregister(chat_id)


async def loop() -> None:
    """One steady clock drives BOTH the colour flip and the progress bar.

    A plain `sleep(EVERY)` drifts: the loop's own work (one Telegram edit per
    panel) is added to every period, so the panel slowly falls out of step.
    The schedule below is monotonic and compensates for that work, keeping
    the colour change and the bar advance locked to the same instant, at a
    steady EVERY-second cadence.
    """
    logger.info("disco: synced tick every %ss (colour + progress together)", EVERY)
    next_at = time.monotonic() + EVERY
    while True:
        delay = next_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        next_at += EVERY + (_penalty if time.time() < _penalty_until else 0.0)
        now = time.monotonic()
        if next_at < now:
            # fell behind (a flood back-off or a slow edit): resync rather
            # than firing a burst of catch-up ticks
            next_at = now + EVERY + (_penalty if time.time() < _penalty_until else 0.0)
        try:
            await _tick()
        except Exception as ex:  # noqa: BLE001
            logger.warning("disco loop: %s", type(ex).__name__)
