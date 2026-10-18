# Changelog

## Unreleased

### Added
- Local-first playback - the lag fix; songs play from disk.
- Yuki API tier, primary for both streaming and downloading.
- Assistant guard - keeps the assistant a member of every served group.
- Disco control panel with a synced colour/progress clock.
- Configurable notice lifetime and pause limit.

### Fixed
- Songs auto-skipped: a cosmetic panel `FloodWait` was treated as a failed
  track by the playback error handler.
- `/skip` stopped working: an unreleased advance claim blocked every later skip.
- Queue position was off by one against the `/queue` listing.
- Search reported "Nothing Found" for real songs when a provider returned an
  empty page, or when YouTube itself returned no results for a bare title.
- Audio break-ups: the ffmpeg pipe was measured draining to 0 B under load.

### Changed
- Control panel restructured to four rows.
- Search prefers the original studio upload over lofi/fan edits.
