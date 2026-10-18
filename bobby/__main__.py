# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import asyncio
import signal
import importlib

from bobby import (anon, app, config, db, logger, queue,
                   stop, tasks, thumb, userbot, yt)
from bobby.core import (assistant_guard, disco, housekeeping, idle_guard,
                        pulse, restrict_gate, status_file)
from bobby.core.spool import spool
from bobby.plugins import all_modules


async def idle():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    except NotImplementedError:
        def handler(sig, frame):
            loop.call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    await stop_event.wait()

async def main():
    # owner's user restriction (/restrict): gate every handler at registration, before any
    # plugin loads — see bobby/plugins/restrict.py
    restrict_gate.hook(app, owner_id=config.OWNER_ID, all_groups=True)
    await db.connect()
    await app.boot()
    await userbot.boot()
    await anon.boot()
    await thumb.start()
    spool.set_pinned(queue.referenced_paths)  # the spool never evicts what a queue still needs
    housekeeping.boot_sweep()  # nothing playing yet — every playback file is an orphan
    asyncio.create_task(housekeeping.janitor())
    asyncio.create_task(idle_guard.watchdog())
    asyncio.create_task(disco.loop())
    asyncio.create_task(assistant_guard.watchdog())
    asyncio.create_task(pulse.loop_lag_monitor())
    status_task = asyncio.create_task(status_file.loop())  # Webview status page feed

    plugin_modules = [
        importlib.import_module(f"bobby.plugins.{module}") for module in all_modules
    ]
    logger.info(f"Loaded {len(all_modules)} modules.")

    # Plugins may opt into a small async startup hook.  Keep those tasks in
    # bobby.tasks so the normal shutdown path cancels them before clients are
    # stopped.  The VC monitor hook only receives the already-running bot;
    # it obtains existing assistants from bobby.userbot and never starts a
    # second session.
    for module in plugin_modules:
        on_start = getattr(module, "on_start", None)
        if callable(on_start):
            tasks.append(asyncio.create_task(on_start(app)))

    if config.COOKIES_URL:
        await yt.save_cookies(config.COOKIES_URL)

    sudoers = await db.get_sudoers()
    app.sudoers.update(sudoers)
    app.bl_users.update(await db.get_blacklisted())
    logger.info(f"Loaded {len(app.sudoers)} sudo users.")

    try:
        await idle()
    finally:
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass
        status_file.mark_offline()
    await stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        raise SystemExit(ex)
