# Security

Never commit `.env`, `*.session`, `cookies.txt`, `downloads/` or any media.

A `.session` file grants **full account access**. If one is ever pushed,
terminate that session immediately from Telegram's *Active Sessions* and
rotate the token.

`.gitignore` blocks all of these. Do not use `git add -f`.
