<div align="center">
  <img src="assets/banner.svg" alt="Mikasa Music Bot" width="100%">
</div>

<div align="center">

[![Stars](https://img.shields.io/github/stars/Igoanet/mikasa-music-bot?style=for-the-badge&logo=github&color=f5c542&labelColor=1a1b27)](https://github.com/Igoanet/mikasa-music-bot/stargazers)
[![Forks](https://img.shields.io/github/forks/Igoanet/mikasa-music-bot?style=for-the-badge&logo=git&color=8b5cf6&labelColor=1a1b27)](https://github.com/Igoanet/mikasa-music-bot/network)
[![Watchers](https://img.shields.io/github/watchers/Igoanet/mikasa-music-bot?style=for-the-badge&logo=eyeball&color=22c55e&labelColor=1a1b27)](https://github.com/Igoanet/mikasa-music-bot/watchers)
[![Views](https://komarev.com/ghpvc/?username=Igoanet&repo=mikasa-music-bot&style=for-the-badge&color=3b82f6&label=VIEWS)](https://github.com/Igoanet/mikasa-music-bot)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![PyTgCalls](https://img.shields.io/badge/PyTgCalls-2.x-ff6b6b?style=for-the-badge)](https://github.com/pytgcalls/pytgcalls)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/Igoanet/mikasa-music-bot?style=for-the-badge&color=orange&labelColor=1a1b27)](https://github.com/Igoanet/mikasa-music-bot/commits/main)
[![Code Size](https://img.shields.io/github/languages/code-size/Igoanet/mikasa-music-bot?style=for-the-badge&color=purple&labelColor=1a1b27)](https://github.com/Igoanet/mikasa-music-bot)

<br>

**🎵 Smooth, jitter‑free music for Telegram voice chats.**

*Local‑first playback · live control panel · a skip that always works*

<br>
</div>

---

<div align="center">

### 📱 What you see when you hit /start

<img src="assets/start-preview.jpg" alt="Mikasa /start" width="620">

<sub>Now‑playing panel: a live progress bar, four clean rows, colours that rotate without ever clashing</sub>

</div>

---

## ✨ Why this bot

Most music bots stutter, skip songs by themselves, and drift out of sync. **Mikasa was built to fix exactly that.**

| | |
|---|---|
| 🎧 **Local‑first playback** | The track is fetched through the API and played **from disk**, so a network blip can never starve the voice chat. |
| 🎛️ **Live control panel** | Progress bar, seek ±15s, replay, pause/resume, next and autoplay across four clean rows. |
| 🌈 **Disco buttons** | Panel colours reshuffle every 2s — randomised so **no two touching buttons ever match**. |
| ⏭️ **A skip that works** | A stale‑claim guard means `/skip` always advances, even after a failed play. |
| 🎚️ **Smarter search** | Prefers the original studio upload — no lofi rips, no fan edits, no promo pre‑rolls. |
| 🌏 **Search that recovers** | If a title returns nothing, the query is broadened instead of reporting *"not found"*. |
| 😴 **Auto‑leave** | A pause is honoured for 5 minutes; the bot leaves after 30 minutes idle. |
| 🤖 **Assistant guard** | Keeps the assistant a member of every group it should serve — and repairs a kick by itself. |

---

## 🎵 Commands

| Command | What it does |
|---|---|
| `/play <song or link>` | Search and play — or queue if something is already going |
| `/pause` · `/resume` | One toggle: **Pause** while playing, **Play** while paused |
| `/skip` | Advance to the next track in the queue |
| `/seek <sec>` · `/seekback [sec]` | Jump forward, or back 15s by default |
| `/queue` | Now playing + everything lined up (text only, no buttons) |
| `/autoplay on\|off` | Let the bot keep the music going when the queue runs dry |
| `/stop` | Stop and leave the voice chat |

---

## 🏗️ How playback chooses a source

```mermaid
graph LR
    Q[/play/] --> S[search]
    S --> P[play_source]
    P --> T1[local file]
    T1 -->|miss| T2[API stream]
    T2 -->|miss| T3[catalogue CDN]
    T3 -->|miss| T4[relay]
    T4 -->|miss| T5[yt-dlp]
    T5 -->|miss| T6[download]
    T6 --> VC[PyTgCalls to voice chat]
```

Every tier falls through to the next, so one dead source costs a song nothing.

**[→ Read the full architecture](ARCHITECTURE.md)** — the state machine, the skip guard, the synced colour clock and the measured `pipe fill` telemetry that drove the local‑first design.

---

## 🚀 Quick start

```bash
git clone https://github.com/Igoanet/mikasa-music-bot
cd mikasa-music-bot

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill it in
python3 -m bobby
```

**Requires `ffmpeg`** on the host.

---

## ⚙️ Configuration

| Variable | Purpose |
|---|---|
| `API_ID` · `API_HASH` | Telegram app credentials |
| `BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | Your numeric Telegram id |
| `SESSION` | Assistant account string session |
| `YUKI_API_KEY` | Music API key for the instant‑stream tier |
| `VC_LOCAL_FIRST` | `true` plays from disk first — recommended |
| `VC_PAUSE_LIMIT` | Seconds a pause stays valid (default `300`) |
| `DISCO_EVERY` | Panel colour interval in seconds (default `2`) |

---

## 📊 Diagnostics

The bot reports its own health, so problems are visible instead of guessed:

```
pulse[-100…] rqc7f6rBTAg: source underruns 0, consumer stalls 0,
   pipe fill avg 58 KB min 40992 B, send gaps 0, socket rx drops 0
```

That line is what proved the stutter was a **starved pipe** (`min 0 B`) and drove the local‑first fix — rather than assuming.

---

## 🤝 Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** — every audio source is a *tier* that returns `None` on failure, and every background job is registered in `__main__.py`.

---

## 🔐 Security

`.env`, `*.session`, `cookies.txt`, `downloads/` and all media are excluded by `.gitignore`.
**A `.session` file grants full account access.**

See **[SECURITY.md](SECURITY.md)**.

---

## 📜 License

MIT — see [LICENSE](LICENSE).

<div align="center">
<br>

**If this bot sounds good in your group, a ⭐ helps others find it.**

<a href="https://github.com/Igoanet/mikasa-music-bot/stargazers">
  <img src="https://img.shields.io/badge/⭐_Star_this_repo-f5c542?style=for-the-badge&labelColor=1a1b27" alt="Star">
</a>

<br><br>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0b1120,100:1e2f63&height=120&section=footer" width="100%">

</div>
