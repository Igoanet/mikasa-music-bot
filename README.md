<p align="center"><img src="assets/banner.svg" alt="Mikasa Music Bot" width="940"></p>
<p align="center">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-2ea043?style=for-the-badge">
  <img alt="python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="telegram" src="https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white">
  <img alt="status" src="https://img.shields.io/badge/status-active-2ea043?style=for-the-badge">
</p>

<h3 align="center">Smooth, jitter-free music for Telegram voice chats.</h3>

<p align="center"><i>Local-first audio · live control panel · reliable skip.</i></p>

---

## Features

| | Feature | Detail |
|---|---|---|
| 🎧 | **Local-first playback** | the track is fetched through the API and played **from disk**, so a network blip can never stutter the voice chat |
| 🎛 | **Live control panel** | progress bar, seek ±15 s, replay, pause/resume, next, autoplay across four clean rows |
| 🌈 | **Disco buttons** | panel colours reshuffle every 2 s — randomised so no two touching buttons ever match |
| ⏭ | **Reliable skip** | a stale-claim guard means `/skip` always advances, even after a failed play |
| 🎚 | **Smarter search** | prefers the original studio upload — no lofi rips, no fan edits, no promo pre-rolls |
| 🌏 | **Search that recovers** | if a title returns nothing, the query is broadened instead of reporting "not found" |
| 😴 | **Auto-leave** | a pause is honoured for 5 minutes, and the bot leaves after 30 minutes idle |
| 🤖 | **Assistant guard** | keeps the assistant a member of every group it should serve |

## Commands

```
/play <song or link>    /pause     /resume    /skip
/queue                  /stop      /seek      /autoplay
```

## Quick start

```bash
git clone https://github.com/<you>/mikasa-music-bot && cd mikasa-music-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then fill it in
python3 -m bobby
```

Requires **ffmpeg** on the host.

## Configuration

| Variable | Purpose |
|---|---|
| `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID` | Telegram credentials |
| `SESSION` | assistant account string session |
| `YUKI_API_KEY` | music API key (a working key is required for the API tier) |
| `VC_LOCAL_FIRST` | `true` plays from disk first (recommended) |

## How playback chooses a source

```
local file  →  API stream  →  catalogue CDN  →  relay  →  yt-dlp  →  download
```

Every tier falls through to the next, so one failing source never stops a song.

## Security

`.env`, `*.session`, `cookies.txt`, `downloads/` and all media are excluded by
`.gitignore`. **A `.session` file grants full account access.**

## License

MIT — see [LICENSE](LICENSE).
