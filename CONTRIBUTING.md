# Contributing

## Layout

```
bobby/
  __main__.py        task wiring - every background job is registered here
  core/              playback engine: calls, youtube, yuki, disco, idle_guard
  helpers/           UI builders and the master/audio helpers
  plugins/           user-facing commands
```

## Rules

- A new audio source is a **tier**, added to the chain in `play_source`, and
  must return `None` on failure rather than raising.
- A new background task is registered in `__main__.py` with `asyncio.create_task`.
- Every network call has a timeout.
- Never let a message-formatting error reach the playback path.

## Verify a change

```bash
python3 -m compileall -q bobby
python3 -m py_compile bobby/core/youtube.py
```

Then play a track and confirm the `pulse[...]` telemetry line reports
`source underruns 0 · consumer stalls 0`.
