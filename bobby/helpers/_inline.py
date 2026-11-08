# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import re

from pyrogram import enums, types

from bobby import app, config, lang
from bobby.core.lang import lang_codes

class Inline:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton
        # Premium animated emoji (document IDs from Telegram's official packs).
        # Icons render only while the bot owner's account has Telegram Premium
        # (server-side check); otherwise buttons show text only, no error.
        from bobby.helpers.emojis import EMOJI_IDS
        self.prem = {
            "cross": EMOJI_IDS["cross"],
            "star": EMOJI_IDS["star"],
            "rocket": EMOJI_IDS["ping"],
            "phone": EMOJI_IDS["tag"],
            "channel": EMOJI_IDS["radio"],
            "play": EMOJI_IDS["play"],
            "pause": EMOJI_IDS["pause"],
            "next": EMOJI_IDS["rnxtcx_door"],
            "replay": EMOJI_IDS["rnxtcx_replay"],
            "mic": EMOJI_IDS["rnxtcx_mic_muted"],
            "mic_active": EMOJI_IDS["rnxtcx_mic"],
            "back": EMOJI_IDS["rnxtcx_backward"],
            "forward": EMOJI_IDS["rnxtcx_forward"],
            "door": EMOJI_IDS["rnxtcx_door"],
            "more": EMOJI_IDS["rnxtcx_more"],
            "disc": EMOJI_IDS["disc"],
            "music": EMOJI_IDS["music"],
            "lightning": EMOJI_IDS["lightning"],
            "add": EMOJI_IDS["add"],
            "sparkle": EMOJI_IDS["sparkle"],
        }

    def cancel_dl(self, text) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(text=text, callback_data=f"cancel_dl",
                       style=enums.ButtonStyle.DANGER,
                       icon_custom_emoji_id=self.prem["cross"])]]
        )

    def controls(
        self,
        chat_id: int,
        status: str = None,
        timer: str = None,
        remove: bool = False,
        autoplay: bool = None,
        _lang: dict = None,
        is_admin: bool = False,
        autoplay_all: bool = False,
        muted: bool = False,
        paused: bool = None,
    ) -> types.InlineKeyboardMarkup:
        """Playback panel -- four rows (owner 2026-10-07).

        Row 1: song details / progress, ALWAYS present.
        Row 2: seek back and forward.
        Row 3: Replay, Pause-Resume, Next  (three buttons only).
        Row 4: Autoplay, a single button.

        Every button carries a DIFFERENT icon: no glyph is reused anywhere on
        the panel.
        """
        rows = []
        head = (status or timer or "").strip()
        if paused is None:
            # Deriving this from the text alone was wrong: row 1 is a
            # progress bar, so the label always said "Pause" and the
            # tap re-sent pause instead of resuming (owner 2026-10-18).
            paused = head.startswith(("\u23f8", "II")) or "\u23f8" in head
        # Keep the displayed line truthful: drop any stale marker and put it
        # back only while actually paused, so row 1 and the button agree.
        for _m in ("\u23f8  ", "\u23f8 ", "II "):
            if head.startswith(_m):
                head = head[len(_m):]
        if paused and head:
            head = "\u23f8 " + head

        # Row 1: the song details / progress line the caller supplies.
        if head:
            rows.append(
                [
                    self.ikb(
                        text=head,
                        callback_data="controls status %s" % chat_id,
                        style=enums.ButtonStyle.DANGER,
                    )
                ]
            )

        if not remove:
            # Row 2 - all 5 player controls in one row (custom emoji icons only):
            # Replay | Seek Backward | Pause/Play | Seek Forward | Next
            rows.append(
                [
                    self.ikb(
                        text="",
                        callback_data="controls replay %s" % chat_id,
                        style=enums.ButtonStyle.DANGER,
                        icon_custom_emoji_id=self.prem["replay"],
                    ),
                    self.ikb(
                        text="",
                        callback_data="controls seekb %s" % chat_id,
                        style=enums.ButtonStyle.DANGER,
                        icon_custom_emoji_id=self.prem["back"],
                    ),
                    self.ikb(
                        text="",
                        callback_data="controls %s %s" % (
                            "resume" if paused else "pause", chat_id),
                        style=enums.ButtonStyle.DANGER,
                        icon_custom_emoji_id=(self.prem["mic_active"] if paused else self.prem["mic"]),
                    ),
                    self.ikb(
                        text="",
                        callback_data="controls seekf %s" % chat_id,
                        style=enums.ButtonStyle.DANGER,
                        icon_custom_emoji_id=self.prem["forward"],
                    ),
                    self.ikb(
                        text="",
                        callback_data="controls skip %s" % chat_id,
                        style=enums.ButtonStyle.DANGER,
                        icon_custom_emoji_id=self.prem["next"],
                    ),
                ]
            )
        return self.ikm(rows)

    def help_markup(
        self, _lang: dict, back: bool = False, staff: bool = False,
        owner: bool = False,
    ) -> types.InlineKeyboardMarkup:
        support_url = config.SUPPORT_CHAT or "https://t.me/toolatetobloom"
        support_handle = support_url.rstrip("/").split("/")[-1]
        if not support_handle.startswith("@"):
            support_handle = f"@{support_handle}"
        owner_url      = config.OWNER_CHAT   or "https://t.me/RohanDevta"
        owner_handle   = owner_url.rstrip("/").split("/")[-1]
        if not owner_handle.startswith("@"):
            owner_handle = f"@{owner_handle}"

        if back:
            rows = [
                [
                    self.ikb(text=_lang["back"], callback_data="help back",
                             style=enums.ButtonStyle.PRIMARY),
                    self.ikb(text=_lang["close"], callback_data="help close",
                             style=enums.ButtonStyle.DANGER,
                             icon_custom_emoji_id=self.prem["cross"]),
                ],
            ]
        else:
            # (label key, callback suffix, colour) — the suffix selects help_<suffix>
            # in the locale file; every entry here needs that key in en.json.
            sections = [
                ("help_5", "play", enums.ButtonStyle.PRIMARY),
                ("help_6", "queue", enums.ButtonStyle.PRIMARY),
                ("help_0", "admins", enums.ButtonStyle.PRIMARY),
                ("help_seek_btn", "seek", enums.ButtonStyle.PRIMARY),
                ("help_loop_btn", "loop", enums.ButtonStyle.PRIMARY),
                ("help_autoplay_btn", "autoplay", enums.ButtonStyle.PRIMARY),
                ("help_speed_btn", "speed", enums.ButtonStyle.PRIMARY),
                ("help_1", "auth", enums.ButtonStyle.PRIMARY),
                ("help_3", "lang", enums.ButtonStyle.PRIMARY),
                ("help_4", "ping", enums.ButtonStyle.PRIMARY),
                ("help_7", "stats", enums.ButtonStyle.PRIMARY),
                ("help_2", "blist", enums.ButtonStyle.PRIMARY),
                ("help_8", "sudo", enums.ButtonStyle.PRIMARY),
                ("help_11", "owner", enums.ButtonStyle.PRIMARY),
            ]
            # blist/sudo/owner stay invisible to everyone but the owner and sudo users
            buttons = [
                self.ikb(text=_lang.get(label, label), callback_data=f"help {cb}", style=style)
                for label, cb, style in sections
                if staff or cb not in ("blist", "sudo", "owner")
            ]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]

        return self.ikm(rows)

    def lang_markup(self, _lang: str) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()

        buttons = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=f"lang_change {code}",
                style=enums.ButtonStyle.PRIMARY,
            )
            for code, name in langs.items()
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        return self.ikm(rows)

    def ping_markup(self, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm([[self.ikb(text=text, url=config.SUPPORT_CHAT,
                                   style=enums.ButtonStyle.PRIMARY)]])

    def play_queued(
        self, chat_id: int, item_id: str, _text: str
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=_text, callback_data=f"controls force {chat_id} {item_id}",
                        style=enums.ButtonStyle.SUCCESS,
                    )
                ]
            ]
        )

    def queue_markup(
        self, chat_id: int, _text: str, playing: bool
    ) -> types.InlineKeyboardMarkup:
        _action = "pause" if playing else "resume"
        _style = (enums.ButtonStyle.SUCCESS if _action == "resume"
                  else enums.ButtonStyle.PRIMARY)
        return self.ikm(
            [[self.ikb(text=("\u23f8  Pause" if playing else "\u25b6  Play"), callback_data=f"controls {_action} {chat_id} q",
                       style=_style)]]
        )

    def settings_markup(
        self, lang: dict, admin_only: bool, cmd_delete: bool, language: str,
        chat_id: int, force_all: bool = False, autoplay: bool = False
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=lang["play_mode"] + " ➜",
                        callback_data="settings",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text=(
                            lang.get("play_admins", "Admins only 🔒")
                            if admin_only
                            else lang.get("play_everyone", "Everyone 🌍")
                        ),
                        # The requested state is explicit.  A stale panel
                        # cannot turn a newer state into the wrong value just
                        # because two owners tapped it at different times.
                        callback_data=(
                            "settings play everyone"
                            if admin_only
                            else "settings play admins"
                        ),
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
                [
                    self.ikb(
                        text=lang.get("force_mode", "Force play") + " ➜",
                        callback_data="settings",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text=(
                            lang.get("force_everyone", "Everyone 🌍")
                            if force_all
                            else lang.get("force_admins", "Admins only 🔒")
                        ),
                        callback_data="settings force",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
                [
                    self.ikb(
                        text=lang.get("autoplay_mode", "Autoplay") + " ➜",
                        callback_data="settings",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text=(
                            lang.get("autoplay_on", "On ✅")
                            if autoplay
                            else lang.get("autoplay_off", "Off ❌")
                        ),
                        callback_data="settings autoplay",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
                [
                    self.ikb(
                        text=lang["cmd_delete"] + " ➜",
                        callback_data="settings",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(text=cmd_delete, callback_data="settings delete",
                             style=enums.ButtonStyle.PRIMARY),
                ],
                [
                    self.ikb(
                        text=lang["language"] + " ➜",
                        callback_data="settings",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(text=lang_codes[language], callback_data="language",
                             style=enums.ButtonStyle.PRIMARY),
                ],
            ]
        )

    def start_key(
        self, lang: dict, private: bool = False, owner: bool = False
    ) -> types.InlineKeyboardMarkup:
        bot_username = getattr(app, 'username', None) or (app.me.username if getattr(app, 'me', None) else 'MikasaMusic_Bot')
        support_url = config.SUPPORT_CHAT or "https://t.me/toolatetobloom"
        support_handle = support_url.rstrip("/").split("/")[-1]
        if not support_handle.startswith("@"):
            support_handle = f"@{support_handle}"
        owner_url      = config.OWNER_CHAT   or "https://t.me/RohanDevta"
        owner_handle   = owner_url.rstrip("/").split("/")[-1]
        if not owner_handle.startswith("@"):
            owner_handle = f"@{owner_handle}"

        rows = [
            [
                self.ikb(
                    text=" Start",
                    callback_data="start_menu",
                    style=enums.ButtonStyle.DANGER,
                    icon_custom_emoji_id="5253944419870062295",
                )
            ],
            [
                self.ikb(
                    text=" Add Me To Group",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                    style=enums.ButtonStyle.PRIMARY,
                    icon_custom_emoji_id=self.prem["add"],
                ),
                self.ikb(
                    text=" Help & Commands",
                    callback_data="help",
                    style=enums.ButtonStyle.PRIMARY,
                    icon_custom_emoji_id=self.prem["sparkle"],
                ),
            ],
        ]
        return self.ikm(rows)

    def recs_markup(
        self,
        items: list[dict],
        seed: str,
        page: int,
        pages: int,
        more_text: str,
        back_text: str,
    ) -> types.InlineKeyboardMarkup:
        """Suggestion card: one green button per related song ("♪ Artist -
        Title", trimmed so it never wraps) and a blue paging row — page one
        shows only "More Songs ?"; once the user has paged forward the row
        splits into "◀ Back" | "More Songs ?", and the last page keeps just
        "◀ Back" (no wrap-around, the list is finite)."""
        rows = [
            [
                self.ikb(
                    text=f"♪ {self._recs_label(item)}",
                    callback_data=f"recs play {seed} {item['id']}",
                    style=enums.ButtonStyle.SUCCESS,
                )
            ]
            for item in items
        ]
        nav = []
        if page > 0:
            nav.append(
                self.ikb(
                    text=back_text,
                    callback_data=f"recs more {seed} {page - 1}",
                    style=enums.ButtonStyle.PRIMARY,
                )
            )
        if page < pages - 1:
            nav.append(
                self.ikb(
                    text=more_text,
                    callback_data=f"recs more {seed} {page + 1}",
                    style=enums.ButtonStyle.PRIMARY,
                )
            )
        if nav:
            rows.append(nav)
        return self.ikm(rows)

    @staticmethod
    def _recs_label(item: dict, width: int = 34) -> str:
        # first two artists are enough to recognise a song; the title keeps
        # whatever room is left so a long artist list can't hide it entirely
        artists = ", ".join(item.get("artists", "").split(", ")[:2]).strip()
        # upload-style titles carry "| Artist | Label" tails and "(Official
        # Video)" / "[4K]" tags — dead weight in a 34-character button
        title = re.split(r"\s*[|｜]\s*", (item.get("title") or "").strip())[0]
        title = re.sub(
            r"\s*[\(\[][^)\]]*\b(?:official|video|lyrics?|audio|4k|hd|full song|"
            r"visuali[sz]er)\b[^)\]]*[\)\]]",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip() or (item.get("title") or "").strip()
        label = f"{artists} - {title}" if artists and title else (title or artists)
        return label if len(label) <= width else label[: width - 1].rstrip() + "…"

    def yt_key(self, link: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(text="❐", copy_text=link,
                             style=enums.ButtonStyle.PRIMARY),
                    self.ikb(text="Youtube", url=link,
                             style=enums.ButtonStyle.PRIMARY),
                ],
            ]
        )
