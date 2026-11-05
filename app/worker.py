"""Run separately from the API: python -m app.worker [--once]."""
import asyncio
import logging
import signal
import sys

from app.db import build_engine, initialize, make_database
from app.jobs import run_once
from app.google_sync import handlers as google_handlers
from app.meta_channels import handlers as meta_handlers
from app.assistant import handlers as assistant_handlers
from app.billing import handlers as billing_handlers


async def main(once=False):
    engine = build_engine()
    initialize(engine)
    database = make_database(engine)
    handlers = {**google_handlers(database), **meta_handlers(database),
                **assistant_handlers(database), **billing_handlers(database)}
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    while not stop.is_set():
        try:
            processed = await run_once(database, handlers)
        except Exception:
            logging.getLogger("secretai.worker").error("Worker poll failed; retrying")
            processed = False
        if once:
            break
        if not processed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except TimeoutError:
                pass
    engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main("--once" in sys.argv))
