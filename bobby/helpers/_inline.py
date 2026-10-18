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
        self.prem = {
            "cross": "5447183459486379525",    # ❌
            "star": "5471952986970267163",     # ⭐
            "rocket": "5312536423174695369",   # 🚀
            "phone": "5294177943033741467",    # 📱
            "channel": "5294117873442037255",  # 📡
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

        # Row 1: the song details / progress line the caller supplies.  No
        # "Now playing" placeholder exists any more (owner 2026-10-07) -- the
        # caller always has the track details while a song is playing.
        if head:
            rows.append(
                [
                    self.ikb(
                        text=head,
                        callback_data="controls status %s" % chat_id,
                        style=enums.ButtonStyle.PRIMARY,
                    )
                ]
            )

        if not remove:
            # Row 2 - seek (rewind / fast-forward pair)
            rows.append(
                [
                    self.ikb(
                        text="\u23ea  -15s",
                        callback_data="controls seekb %s" % chat_id,
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text="+15s  \u23e9",
                        callback_data="controls seekf %s" % chat_id,
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ]
            )
            # Row 3 - exactly three buttons
            rows.append(
                [
                    self.ikb(
                        text="\U0001f504  Replay",
                        callback_data="controls replay %s" % chat_id,
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text=("\u25b6  Play" if paused else "\u23f8  Pause"),
                        callback_data="controls %s %s" % (
                            "resume" if paused else "pause", chat_id),
                        style=enums.ButtonStyle.DANGER,
                    ),
                    self.ikb(
                        text="\u23ed  Next",
                        callback_data="controls skip %s" % chat_id,
                        style=enums.ButtonStyle.SUCCESS,
                    ),
                ]
            )
            # Row 4 - autoplay on its own
            if autoplay is not None and (is_admin or autoplay_all):
                _lang = _lang or {}
                rows.append(
                    [
                        self.ikb(
                            text=_lang.get(
                                "autoplay_btn_on" if autoplay else "autoplay_btn_off",
                                "\u267e\ufe0f Autoplay: On" if autoplay
                                else "\u267e\ufe0f Autoplay: Off",
                            ),
                            callback_data="controls autoplay %s" % chat_id,
                            style=(enums.ButtonStyle.SUCCESS if autoplay
                                   else enums.ButtonStyle.PRIMARY),
                        )
                    ]
                )
        return self.ikm(rows)

    def help_markup(
        self, _lang: dict, back: bool = False, staff: bool = False,
        owner: bool = False,
    ) -> types.InlineKeyboardMarkup:
        if back:
            rows = [
                [
                    self.ikb(text=_lang["back"], callback_data="help back",
                             style=enums.ButtonStyle.PRIMARY),
                    self.ikb(text=_lang["close"], callback_data="help close",
                             style=enums.ButtonStyle.DANGER,
                             icon_custom_emoji_id=self.prem["cross"]),
                ]
            ]
        else:
            # (label key, callback suffix, colour) — the suffix selects help_<suffix>
            # in the locale file; every entry here needs that key in en.json.
            sections = [
                ("help_5", "play", enums.ButtonStyle.PRIMARY),
                ("help_9", "voice", enums.ButtonStyle.SUCCESS),
                ("help_10", "clone", enums.ButtonStyle.SUCCESS),
                ("help_6", "queue", enums.ButtonStyle.PRIMARY),
                ("help_0", "admins", enums.ButtonStyle.PRIMARY),
                ("help_1", "auth", enums.ButtonStyle.PRIMARY),
                ("help_2", "blist", enums.ButtonStyle.PRIMARY),
                ("help_3", "lang", enums.ButtonStyle.PRIMARY),
                ("help_4", "ping", enums.ButtonStyle.PRIMARY),
                ("help_7", "stats", enums.ButtonStyle.PRIMARY),
                ("help_8", "sudo", enums.ButtonStyle.PRIMARY),
                ("help_11", "owner", enums.ButtonStyle.PRIMARY),
            ]
            # clone/blist/sudo/owner stay invisible to everyone but the owner and sudo users
            buttons = [
                self.ikb(text=_lang[label], callback_data=f"help {cb}", style=style)
                for label, cb, style in sections
                if staff or cb not in ("clone", "blist", "sudo", "owner")
            ]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]

        if owner and not back:
            # the owner can open the panel from here too
            rows.append([self.ikb(text="👑 Owner Panel",
                                  callback_data="own_panel",
                                  style=enums.ButtonStyle.PRIMARY)])
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
        rows = [
            [
                self.ikb(
                    text=lang["add_me"],
                    url=f"https://t.me/{app.username}?startgroup=true",
                    style=enums.ButtonStyle.SUCCESS,
                    icon_custom_emoji_id=self.prem["rocket"],
                )
            ],
            [self.ikb(text=lang["help"], callback_data="help",
                      style=enums.ButtonStyle.PRIMARY,
                      icon_custom_emoji_id=self.prem["star"])],
            [
                self.ikb(text=lang["support"], url=config.SUPPORT_CHAT,
                         style=enums.ButtonStyle.PRIMARY,
                         icon_custom_emoji_id=self.prem["phone"]),
                self.ikb(text=lang["channel"], url=config.SUPPORT_CHANNEL,
                         style=enums.ButtonStyle.PRIMARY,
                         icon_custom_emoji_id=self.prem["channel"]),
            ],
        ]
        if private and owner:
            # owner panel entry point — shown only to the owner
            rows += [
                [self.ikb(text="👑 Owner Panel", callback_data="own_panel",
                          style=enums.ButtonStyle.PRIMARY)]
            ]
        if not private:
            rows += [[self.ikb(text=lang["language"], callback_data="language",
                               style=enums.ButtonStyle.PRIMARY)]]
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
