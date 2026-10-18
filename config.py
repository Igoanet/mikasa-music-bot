from os import getenv
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.API_ID = int(getenv("API_ID", 0))
        self.API_HASH = getenv("API_HASH")

        self.BOT_TOKEN = getenv("BOT_TOKEN")
        self.MONGO_URL = getenv("MONGO_URL")

        try:
            self.LOGGER_ID = int(getenv("LOGGER_ID", "") or 0)
        except ValueError:
            self.LOGGER_ID = 0  # no log group configured — logging is skipped
        self.OWNER_ID = int(getenv("OWNER_ID", 0))

        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", 60)) * 60
        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", 20))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", 20))

        self.SESSION1 = getenv("SESSION", None)
        self.SESSION2 = getenv("SESSION2", None)
        self.SESSION3 = getenv("SESSION3", None)

        self.SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/rohanDevta")
        self.SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/toolatetobloom")

        # Yuki Music API (owner 2026-10-04): YouTube audio through the
        # gateway instead of yt-dlp hitting YouTube's bot-wall.
        self.YUKI_API_URL = getenv("YUKI_API_URL", "https://music.yukiapi.site")
        self.YUKI_API_BACKUP = getenv("YUKI_API_BACKUP", "https://play.yukiapi.site")
        self.YUKI_API_KEY = getenv("YUKI_API_KEY", "")

        self.AUTO_LEAVE: bool = getenv("AUTO_LEAVE", "False").lower() == "true"
        self.AUTO_END: bool = getenv("AUTO_END", "False").lower() == "true"
    
        self.THUMB_GEN: bool = getenv("THUMB_GEN", "True").lower() == "true"
        self.VIDEO_PLAY: bool = getenv("VIDEO_PLAY", "True").lower() == "true"

        self.LANG_CODE = getenv("LANG_CODE", "en")

        self.COOKIES_URL = [
            url for url in getenv("COOKIES_URL", "").split(" ")
            if url and "batbin.me" in url
        ]
        self.DEFAULT_THUMB = getenv("DEFAULT_THUMB", "https://te.legra.ph/file/3e40a408286d4eda24191.jpg")
        self.PING_IMG = getenv("PING_IMG", "https://files.catbox.moe/haagg2.png")
        self.START_IMG = getenv("START_IMG", "https://files.catbox.moe/zvziwk.jpg")

    def check(self):
        missing = [
            var
            # SESSION is NOT required: assistants are added in-bot via
            # /accounts (session string), persisted in data/sessions.json.
            # MONGO_URL is unused: storage is a local JSON file (core/mongo.py).
            # LOGGER_ID is optional: 0 disables log-group messages.
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
