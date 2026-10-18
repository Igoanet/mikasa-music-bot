import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Track:
    def __init__(self, **values):
        self.__dict__.update(values)


class YouTubeSearchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bobby",
                "bobby.core",
                "bobby.core.audius",
                "bobby.core.jiosaavn",
                "bobby.core.spool",
                "bobby.helpers",
                "py_yt",
                "yt_dlp",
            )
        }

        bobby = types.ModuleType("bobby")
        bobby.config = types.SimpleNamespace(DURATION_LIMIT=3600)
        bobby.logger = logging.getLogger("youtube-search-test")

        core = types.ModuleType("bobby.core")
        core.__path__ = []

        audius = types.ModuleType("bobby.core.audius")
        audius.audius = types.SimpleNamespace()

        jiosaavn = types.ModuleType("bobby.core.jiosaavn")
        jiosaavn.clean_query = lambda query: query
        jiosaavn.is_copy = lambda text, query="": False
        jiosaavn.saavn = types.SimpleNamespace()

        spool = types.ModuleType("bobby.core.spool")
        spool.spool = types.SimpleNamespace()

        helpers = types.ModuleType("bobby.helpers")
        helpers.Track = _Track
        helpers.utils = types.SimpleNamespace(
            to_seconds=lambda value: sum(
                int(part) * 60**index
                for index, part in enumerate(reversed(value.split(":")))
            )
        )

        py_yt = types.ModuleType("py_yt")
        py_yt.Playlist = object
        py_yt.VideosSearch = object

        sys.modules.update(
            {
                "bobby": bobby,
                "bobby.core": core,
                "bobby.core.audius": audius,
                "bobby.core.jiosaavn": jiosaavn,
                "bobby.core.spool": spool,
                "bobby.helpers": helpers,
                "py_yt": py_yt,
                "yt_dlp": types.ModuleType("yt_dlp"),
            }
        )

        spec = importlib.util.spec_from_file_location(
            "bobby_test_youtube", ROOT / "bobby" / "core" / "youtube.py"
        )
        cls.youtube_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.youtube_module
        spec.loader.exec_module(cls.youtube_module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("bobby_test_youtube", None)

    async def asyncSetUp(self):
        self.youtube = self.youtube_module.YouTube()

    async def asyncTearDown(self):
        self.youtube._dl_pool.shutdown(wait=True)

    async def test_text_search_returns_youtube_top_result_without_catalogue(self):
        calls = []
        top_id = "TOPTOPTOP01"

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                calls.append((query, limit, with_live))

            async def next(self):
                return {
                    "result": [
                        {
                            "id": top_id,
                            "title": "YouTube top hit",
                            "duration": "3:00",
                            "channel": {"name": "Top channel"},
                            "thumbnails": [{"url": "https://img/top?size=1"}],
                            "link": f"https://www.youtube.com/watch?v={top_id}",
                            "viewCount": {"short": "1M views"},
                        },
                        {
                            "id": "SECONDHIT01",
                            "title": "Second result",
                            "duration": "4:00",
                            "channel": {"name": "Other channel"},
                            "thumbnails": [{"url": "https://img/second"}],
                            "link": "https://www.youtube.com/watch?v=SECONDHIT01",
                            "viewCount": {"short": "2M views"},
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("a scene", 7)

        self.assertEqual(track.id, top_id)
        self.assertEqual(calls, [("a scene", self.youtube_module._SEARCH_LIMIT, False)])

    async def test_indian_query_uses_indian_market_and_skips_a_cover(self):
        locales = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                locales.append((language, region))

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "COVERVERS01",
                            "title": "Tera Ishq - cover by a fan",
                            "duration": "3:10",
                            "channel": {"name": "Random uploads"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=COVERVERS01",
                        },
                        {
                            "id": "REALSONG001",
                            "title": "Tera Ishq | Full Song",
                            "duration": "4:05",
                            "channel": {"name": "T-Series"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REALSONG001",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("tera ishq", 21)

        self.assertEqual(track.id, "REALSONG001")
        self.assertEqual(locales, [("hi", "IN")])

    async def test_english_query_keeps_the_english_market_and_top_hit(self):
        locales = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                locales.append((language, region))

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "ENGLISH0001",
                            "title": "Shape of You",
                            "duration": "4:23",
                            "channel": {"name": "Ed Sheeran"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=ENGLISH0001",
                        },
                        {
                            "id": "HINDIDUB001",
                            "title": "शेप ऑफ यू हिंदी वर्जन",
                            "duration": "4:00",
                            "channel": {"name": "Covers channel"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=HINDIDUB001",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("shape of you", 22)

        self.assertEqual(track.id, "ENGLISH0001")
        self.assertEqual(locales, [("en", "US")])

    async def test_requested_remix_is_not_penalised(self):
        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "REMIXVER001",
                            "title": "Dilbar Remix",
                            "duration": "3:30",
                            "channel": {"name": "DJ uploads"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REMIXVER001",
                        },
                        {
                            "id": "ORIGINAL001",
                            "title": "Dilbar",
                            "duration": "3:20",
                            "channel": {"name": "T-Series"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=ORIGINAL001",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("dilbar remix", 23)

        self.assertEqual(track.id, "REMIXVER001")

    async def test_mashup_at_the_top_loses_to_the_song_that_was_named(self):
        """The request's words are in the mashup title too — what rules it
        out is everything else the title adds."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "MASHUPVER11",
                            "title": "Tum Hi Ho x Channa Mereya | Love Mashup 2024",
                            "duration": "6:40",
                            "channel": {"name": "Mashup World"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=MASHUPVER11",
                        },
                        {
                            "id": "REALTUMHI11",
                            "title": "Tum Hi Ho | Full Song",
                            "duration": "4:22",
                            "channel": {"name": "T-Series"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REALTUMHI11",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("tum hi ho", 31)

        self.assertEqual(track.id, "REALTUMHI11")

    async def test_a_shorter_title_alone_cannot_move_the_pick(self):
        """Credits in a title are how real releases are named — a tidier
        upload below them is not evidence that the top hit is wrong."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "ARTISTCRD11",
                            "title": (
                                "Kesariya Brahmastra Ranbir Kapoor Alia Bhatt "
                                "Pritam Arijit Singh"
                            ),
                            "duration": "4:28",
                            "channel": {"name": "Arijit Singh"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=ARTISTCRD11",
                        },
                        {
                            "id": "KESARIYA011",
                            "title": "Kesariya",
                            "duration": "4:20",
                            "channel": {"name": "Fan Uploads"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=KESARIYA011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("kesariya", 32)

        self.assertEqual(track.id, "ARTISTCRD11")

    async def test_request_filler_words_do_not_decide_the_pick(self):
        """"play the song perfect" is a request for "Perfect"."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "SONGWORD011",
                            "title": "Best Song Ever",
                            "duration": "3:20",
                            "channel": {"name": "Song Hits"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=SONGWORD011",
                        },
                        {
                            "id": "PERFECT0011",
                            "title": "Perfect",
                            "duration": "4:23",
                            "channel": {"name": "Ed Sheeran"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=PERFECT0011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("play the song perfect", 33)

        self.assertEqual(track.id, "PERFECT0011")

    async def test_named_artist_channel_wins_over_a_look_alike_upload(self):
        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "FANUPLOAD11",
                            "title": "Believer (Rock Version)",
                            "duration": "3:40",
                            "channel": {"name": "Guitar Covers Daily"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=FANUPLOAD11",
                        },
                        {
                            "id": "BELIEVER011",
                            "title": "Believer",
                            "duration": "3:24",
                            "channel": {"name": "ImagineDragons"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=BELIEVER011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("believer imagine dragons", 34)

        self.assertEqual(track.id, "BELIEVER011")

    async def test_reaction_video_at_the_top_is_not_played(self):
        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "REACTION011",
                            "title": "Chaleya - reaction",
                            "duration": "8:00",
                            "channel": {"name": "Reaction Hub"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REACTION011",
                        },
                        {
                            "id": "CHALEYA0011",
                            "title": "Chaleya",
                            "duration": "3:15",
                            "channel": {"name": "Sony Music India"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=CHALEYA0011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("chaleya", 35)

        self.assertEqual(track.id, "CHALEYA0011")

    async def test_top_hit_still_wins_when_nothing_below_matches_better(self):
        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "TOPRESULT11",
                            "title": "Apna Bana Le",
                            "duration": "4:01",
                            "channel": {"name": "Zee Music Company"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=TOPRESULT11",
                        },
                        {
                            "id": "SECONDONE11",
                            "title": "Apna Bana Le",
                            "duration": "4:01",
                            "channel": {"name": "Zee Music Company"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=SECONDONE11",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("apna bana le", 36)

        self.assertEqual(track.id, "TOPRESULT11")

    async def test_a_title_made_of_filler_words_still_wins(self):
        """"song 2 blur" names the song "Song 2" — the words "song" and "2"
        are part of the title, not request filler to be ignored."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "SONGTWO0011",
                            "title": "Song 2",
                            "duration": "2:02",
                            "channel": {"name": "Blur"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=SONGTWO0011",
                        },
                        {
                            "id": "COFFEETV011",
                            "title": "Blur - Coffee & TV",
                            "duration": "5:58",
                            "channel": {"name": "Blur"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=COFFEETV011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("song 2 blur", 37)

        self.assertEqual(track.id, "SONGTWO0011")

    async def test_official_credit_heavy_title_beats_a_clean_fan_upload(self):
        """Label uploads carry movie/cast/composer credits — that extra text
        must not hand the play to a tidier fan upload."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "OFFICIAL011",
                            "title": (
                                "Kesariya (Full Video) Brahmastra | Ranbir Kapoor | "
                                "Alia Bhatt | Pritam | Arijit Singh | Amitabh"
                            ),
                            "duration": "4:28",
                            "channel": {"name": "Sony Music India"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=OFFICIAL011",
                        },
                        {
                            "id": "FANCLEAN011",
                            "title": "Kesariya",
                            "duration": "4:20",
                            "channel": {"name": "Music Lover"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=FANCLEAN011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("kesariya", 38)

        self.assertEqual(track.id, "OFFICIAL011")

    async def test_one_letter_song_title_is_not_lost(self):
        """"i kendrick lamar" asks for the song "i" — a one-letter title is
        still the title."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "SONGIONE011",
                            "title": "i",
                            "duration": "5:36",
                            "channel": {"name": "KendrickLamarVEVO"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=SONGIONE011",
                        },
                        {
                            "id": "HUMBLEONE11",
                            "title": "Kendrick Lamar - HUMBLE.",
                            "duration": "3:11",
                            "channel": {"name": "KendrickLamarVEVO"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=HUMBLEONE11",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("i kendrick lamar", 39)

        self.assertEqual(track.id, "SONGIONE011")

    async def test_a_generic_music_channel_is_not_a_reason_to_move_the_pick(self):
        """"Music"/"Records" in a channel name proves nothing — only the
        words decide, so an equally matching top hit keeps the play."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "ARTISTTOP11",
                            "title": "Chaleya (Full Song)",
                            "duration": "3:15",
                            "channel": {"name": "Arijit Singh"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=ARTISTTOP11",
                        },
                        {
                            "id": "FANMUSIC011",
                            "title": "Chaleya",
                            "duration": "3:14",
                            "channel": {"name": "Trending Music Records"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=FANMUSIC011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("chaleya", 40)

        self.assertEqual(track.id, "ARTISTTOP11")

    async def test_query_word_order_alone_cannot_move_the_pick(self):
        """Users type "song artist"; releases are titled "Artist - Song".
        That difference is not a reason to leave YouTube's top result."""

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "OFFICIALBL1",
                            "title": "Imagine Dragons - Believer",
                            "duration": "3:24",
                            "channel": {"name": "ImagineDragonsVEVO"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=OFFICIALBL1",
                        },
                        {
                            "id": "FANORDER011",
                            "title": "Believer Imagine Dragons",
                            "duration": "3:22",
                            "channel": {"name": "Fan Uploads"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=FANORDER011",
                        },
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("believer imagine dragons", 41)

        self.assertEqual(track.id, "OFFICIALBL1")

    async def test_standard_youtube_url_bypasses_text_search(self):
        search_called = False
        direct_calls = []

        class UnexpectedSearch:
            def __init__(self, *args, **kwargs):
                nonlocal search_called
                search_called = True

            async def next(self):
                raise AssertionError("a standard YouTube URL must not be searched")

        async def direct_track(url, message_id, video=False):
            direct_calls.append((url, message_id, video))
            return _Track(id="dQw4w9WgXcQ", title="direct")

        self.youtube_module.VideosSearch = UnexpectedSearch
        self.youtube.track_from_url = direct_track
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        track = await self.youtube.search(url, 9)

        self.assertEqual(track.id, "dQw4w9WgXcQ")
        self.assertEqual(direct_calls, [(url, 9, False)])
        self.assertFalse(search_called)

    async def test_multiline_lyrics_are_normalized_before_top_hit_search(self):
        calls = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                calls.append((query, limit, with_live))

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "LYRICSTOP01",
                            "title": "A song from the lyric fragment",
                            "duration": "3:00",
                            "channel": {"name": "Official channel"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=LYRICSTOP01",
                        }
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search(
            "  hello darkness\n  my old friend  ", 11
        )

        self.assertEqual(track.id, "LYRICSTOP01")
        self.assertEqual(
            calls,
            [("hello darkness my old friend", self.youtube_module._SEARCH_LIMIT, False)],
        )

    async def test_lyric_fallback_adds_hint_only_after_non_song_top_hit(self):
        calls = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                calls.append(query)

            async def next(self):
                query = calls[-1]
                if query.endswith("lyrics"):
                    return {
                        "result": [
                            {
                                "id": "LYRICSOK001",
                                "title": "The proper song",
                                "duration": "3:00",
                                "channel": {"name": "Artist"},
                                "thumbnails": [],
                                "link": "https://www.youtube.com/watch?v=LYRICSOK001",
                            }
                        ]
                    }
                return {
                    "result": [
                        {
                            "id": "REACTION001",
                            "title": "Reaction to the lyric fragment",
                            "duration": "8:00",
                            "channel": {"name": "Commentary"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REACTION001",
                        }
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search(
            "when you try your best but you don't succeed", 12
        )

        self.assertEqual(track.id, "LYRICSOK001")
        self.assertEqual(
            calls,
            [
                "when you try your best but you don't succeed",
                "when you try your best but you don't succeed lyrics",
            ],
        )

    async def test_invalid_provider_id_cannot_turn_lyrics_into_video_id(self):
        calls = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                calls.append(query)

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "hello darkness my old friend",
                            "title": "Malformed provider payload",
                        }
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("hello darkness my old friend", 13)

        self.assertIsNone(track)
        self.assertEqual(calls, ["hello darkness my old friend"])

    async def test_ambiguous_lyric_result_is_not_played_as_a_song(self):
        calls = []

        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                calls.append(query)

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "REACTION001",
                            "title": "Reaction to this lyric fragment",
                            "duration": "8:00",
                            "channel": {"name": "Commentary"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=REACTION001",
                        }
                    ]
                } if len(calls) == 1 else {"result": []}

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search(
            "please identify this song when you try your best", 14
        )

        self.assertIsNone(track)
        self.assertEqual(
            calls,
            [
                "please identify this song when you try your best",
                "please identify this song when you try your best lyrics",
            ],
        )

    async def test_search_result_link_cannot_override_returned_video_id(self):
        class FakeVideosSearch:
            def __init__(self, query, limit, with_live, language=None, region=None):
                pass

            async def next(self):
                return {
                    "result": [
                        {
                            "id": "BOUNDVID001",
                            "title": "Bound result",
                            "duration": "3:00",
                            "channel": {"name": "Artist"},
                            "thumbnails": [],
                            "link": "https://www.youtube.com/watch?v=OTHERID0001",
                        }
                    ]
                }

        self.youtube_module.VideosSearch = FakeVideosSearch
        track = await self.youtube.search("Bound title", 15)

        self.assertEqual(track.id, "BOUNDVID001")
        self.assertEqual(
            track.url,
            "https://www.youtube.com/watch?v=BOUNDVID001",
        )

    async def test_live_resolution_validates_feed_and_keeps_live_identity(self):
        calls = []
        ready_calls = []
        feed = "https://manifest.googlevideo.com/live-feed"

        class FakeYoutubeDL:
            def __init__(self, options):
                calls.append(options)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "id": "2qsYNs7GpPo",
                    "is_live": True,
                    "live_status": "is_live",
                    "protocol": "m3u8_native",
                    "url": feed,
                    "uploader": "Live channel",
                    "title": "Public live stream",
                    "thumbnail": "https://img/live.jpg?size=1",
                }

        old_ytdlp = getattr(self.youtube_module.yt_dlp, "YoutubeDL", None)
        self.youtube_module.yt_dlp.YoutubeDL = FakeYoutubeDL
        self.youtube.get_cookies = lambda: None

        async def low_cpu(func, *args):
            return func(*args)

        async def ready(url, protocol):
            ready_calls.append((url, protocol))
            return True

        self.youtube._low_cpu = low_cpu
        self.youtube._live_feed_ready = ready
        try:
            track = await self.youtube.get_live(
                "https://www.youtube.com/live/2qsYNs7GpPo", 17
            )
        finally:
            if old_ytdlp is None:
                del self.youtube_module.yt_dlp.YoutubeDL
            else:
                self.youtube_module.yt_dlp.YoutubeDL = old_ytdlp

        self.assertIsNotNone(track)
        self.assertEqual(track.id, "2qsYNs7GpPo")
        self.assertEqual(track.file_path, feed)
        self.assertEqual(track.duration, "🔴 LIVE")
        self.assertEqual(track.duration_sec, 0)
        self.assertEqual(track.view_count, "LIVE")
        self.assertEqual(track.url, "https://www.youtube.com/watch?v=2qsYNs7GpPo")
        self.assertEqual(ready_calls, [(feed, "m3u8_native")])
        self.assertEqual(calls[0]["noplaylist"], True)
        self.assertIn("height<=480", calls[0]["format"])

    async def test_live_resolution_rotates_after_dead_feed(self):
        feeds = [
            "https://manifest.googlevideo.com/dead-feed",
            "https://manifest.googlevideo.com/working-feed",
        ]
        ready_calls = []
        probe_calls = []

        class FakeYoutubeDL:
            def __init__(self, options):
                probe_calls.append(options["extractor_args"])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "id": "2qsYNs7GpPo",
                    "is_live": True,
                    "live_status": "is_live",
                    "protocol": "m3u8_native",
                    "url": feeds[len(probe_calls) - 1],
                    "title": "Public live stream",
                }

        old_ytdlp = getattr(self.youtube_module.yt_dlp, "YoutubeDL", None)
        self.youtube_module.yt_dlp.YoutubeDL = FakeYoutubeDL
        self.youtube.get_cookies = lambda: None

        async def low_cpu(func, *args):
            return func(*args)

        async def ready(url, protocol):
            ready_calls.append(url)
            return url.endswith("working-feed")

        self.youtube._low_cpu = low_cpu
        self.youtube._live_feed_ready = ready
        try:
            track = await self.youtube.get_live(
                "https://www.youtube.com/live/2qsYNs7GpPo", 18
            )
        finally:
            if old_ytdlp is None:
                del self.youtube_module.yt_dlp.YoutubeDL
            else:
                self.youtube_module.yt_dlp.YoutubeDL = old_ytdlp

        self.assertEqual(track.file_path, feeds[1])
        self.assertEqual(ready_calls, feeds)
        self.assertEqual(len(probe_calls), 2)

    async def test_live_identity_survives_later_non_live_client_result(self):
        feed = "https://manifest.googlevideo.com/dead-feed"
        probe_calls = []

        class FakeYoutubeDL:
            def __init__(self, options):
                probe_calls.append(options["extractor_args"])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                if len(probe_calls) == 1:
                    return {
                        "id": "2qsYNs7GpPo",
                        "is_live": True,
                        "live_status": "is_live",
                        "protocol": "m3u8_native",
                        "url": feed,
                        "title": "Public live stream",
                    }
                return {
                    "id": "2qsYNs7GpPo",
                    "is_live": False,
                    "live_status": "was_live",
                    "url": "https://cdn.example/old-vod",
                }

        old_ytdlp = getattr(self.youtube_module.yt_dlp, "YoutubeDL", None)
        self.youtube_module.yt_dlp.YoutubeDL = FakeYoutubeDL
        self.youtube.get_cookies = lambda: None

        async def low_cpu(func, *args):
            return func(*args)

        async def ready(url, protocol):
            return False

        self.youtube._low_cpu = low_cpu
        self.youtube._live_feed_ready = ready
        try:
            track = await self.youtube.get_live(
                "https://www.youtube.com/watch?v=2qsYNs7GpPo", 20
            )
        finally:
            if old_ytdlp is None:
                del self.youtube_module.yt_dlp.YoutubeDL
            else:
                self.youtube_module.yt_dlp.YoutubeDL = old_ytdlp

        self.assertIsNotNone(track)
        self.assertEqual(track.id, "2qsYNs7GpPo")
        self.assertEqual(track.url, "https://www.youtube.com/watch?v=2qsYNs7GpPo")
        self.assertEqual(track.duration, "🔴 LIVE")
        self.assertEqual(track.view_count, "LIVE")
        self.assertIsNone(track.file_path)
        self.assertEqual(len(probe_calls), 3)

    async def test_live_feed_readiness_bounds_hls_probe_to_three_seconds(self):
        calls = []
        options = []

        class FinishedProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b'{"streams":[{"codec_type":"video"},'
                    b'{"codec_type":"audio","codec_name":"aac"}]}',
                    b"",
                )

        async def spawn(*args, **kwargs):
            calls.append(args)
            options.append(kwargs)
            return FinishedProcess()

        old_spawn = self.youtube_module.asyncio.create_subprocess_exec
        self.youtube_module.asyncio.create_subprocess_exec = spawn
        try:
            ready = await self.youtube_module.YouTube._live_feed_ready(
                "https://manifest.googlevideo.com/live-feed",
                "m3u8_native",
            )
        finally:
            self.youtube_module.asyncio.create_subprocess_exec = old_spawn

        self.assertTrue(ready)
        command = calls[0]
        self.assertEqual(command[0], "ffprobe")
        self.assertNotIn("-nostdin", command)
        self.assertEqual(options[0]["stdin"], asyncio.subprocess.DEVNULL)
        self.assertIn("-analyzeduration", command)
        self.assertIn("-probesize", command)
        self.assertIn("-rw_timeout", command)
        self.assertEqual(command[command.index("-read_intervals") + 1], "%+3")

    async def test_live_feed_readiness_cancellation_kills_and_reaps_probe(self):
        class HangingProcess:
            def __init__(self):
                self.returncode = None
                self.killed = False
                self.communicate_calls = 0

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def communicate(self):
                self.communicate_calls += 1
                if self.killed:
                    return b"", b""
                await asyncio.Future()

        process = HangingProcess()

        async def spawn(*args, **kwargs):
            return process

        old_spawn = self.youtube_module.asyncio.create_subprocess_exec
        self.youtube_module.asyncio.create_subprocess_exec = spawn
        try:
            pending = asyncio.create_task(
                self.youtube_module.YouTube._live_feed_ready(
                    "https://manifest.googlevideo.com/live-feed",
                    "m3u8_native",
                )
            )
            while process.communicate_calls == 0:
                await asyncio.sleep(0)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        finally:
            self.youtube_module.asyncio.create_subprocess_exec = old_spawn

        self.assertTrue(process.killed)
        self.assertEqual(process.communicate_calls, 2)

    async def test_non_live_url_stays_on_ordinary_vod_path(self):
        ready_called = False

        class FakeYoutubeDL:
            def __init__(self, options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "id": "2qsYNs7GpPo",
                    "is_live": False,
                    "live_status": "was_live",
                    "url": "https://cdn.example/vod",
                }

        old_ytdlp = getattr(self.youtube_module.yt_dlp, "YoutubeDL", None)
        self.youtube_module.yt_dlp.YoutubeDL = FakeYoutubeDL
        self.youtube.get_cookies = lambda: None

        async def low_cpu(func, *args):
            return func(*args)

        async def ready(url, protocol):
            nonlocal ready_called
            ready_called = True
            return True

        self.youtube._low_cpu = low_cpu
        self.youtube._live_feed_ready = ready
        try:
            track = await self.youtube.get_live(
                "https://www.youtube.com/watch?v=2qsYNs7GpPo", 19
            )
        finally:
            if old_ytdlp is None:
                del self.youtube_module.yt_dlp.YoutubeDL
            else:
                self.youtube_module.yt_dlp.YoutubeDL = old_ytdlp

        self.assertIsNone(track)
        self.assertFalse(ready_called)

    async def test_queued_live_track_refreshes_signed_feed_at_play_time(self):
        calls = []
        refreshed = "https://manifest.googlevideo.com/refreshed-feed"
        track = _Track(
            id="2qsYNs7GpPo",
            duration="🔴 LIVE",
            duration_sec=0,
            view_count="LIVE",
            url="https://www.youtube.com/watch?v=2qsYNs7GpPo",
            message_id=21,
            file_path=None,
        )

        async def refresh(url, message_id, video=False):
            calls.append((url, message_id, video))
            return _Track(
                id="2qsYNs7GpPo",
                duration="🔴 LIVE",
                duration_sec=0,
                view_count="LIVE",
                title="Public live stream",
                thumbnail="https://img/live.jpg",
                file_path=refreshed,
            )

        self.youtube.get_live = refresh
        result = await self.youtube.play_source(track)

        self.assertEqual(result, refreshed)
        self.assertEqual(
            calls,
            [("https://www.youtube.com/watch?v=2qsYNs7GpPo", 21, False)],
        )
        self.assertEqual(track.file_path, refreshed)
        self.assertEqual(track.duration, "🔴 LIVE")
        self.assertEqual(track.duration_sec, 0)


if __name__ == "__main__":
    unittest.main()
