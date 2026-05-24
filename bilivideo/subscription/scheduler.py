"""Periodic check loop for subscription updates.

Improvements over the previous single-tick loop:
  * Per-iteration jitter so several plugin instances don't sync up.
  * Errors in one UP don't abort the rest of the cycle.
  * The loop is fully cancellable on plugin termination.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable

from ..core.logging import get_logger
from .manager import Subscription, SubscriptionManager

logger = get_logger("BiliVideo/Scheduler")

CheckCallback = Callable[[str, Subscription], Awaitable[None]]


class CheckScheduler:
    """Wraps an asyncio task that polls the subscription manager."""

    def __init__(
        self,
        manager: SubscriptionManager,
        callback: CheckCallback,
        *,
        interval_seconds: int,
        startup_delay: float = 10.0,
        per_request_pause: float = 2.0,
    ) -> None:
        self._manager = manager
        self._callback = callback
        self._interval = interval_seconds
        self._startup_delay = startup_delay
        self._per_request_pause = per_request_pause
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running():
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def trigger_once(self) -> int:
        """Run a single check pass synchronously, returning a count of new
        videos pushed. Useful for the `/检查更新` command."""

        return await self._scan_all()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._startup_delay)
        except asyncio.CancelledError:
            return

        while self._running:
            try:
                await self._scan_all()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error(f"scheduler iteration failed: {exc}", exc_info=True)
            jitter = random.uniform(0, max(1.0, self._interval * 0.05))
            try:
                await asyncio.sleep(self._interval + jitter)
            except asyncio.CancelledError:
                return

    async def _scan_all(self) -> int:
        all_subs = await self._manager.all_subscriptions()
        if not all_subs:
            return 0

        total = sum(len(v) for v in all_subs.values())
        logger.info(f"running scheduled check across {len(all_subs)} sessions ({total} subs)")

        triggered = 0
        for origin, ups in all_subs.items():
            for up in ups:
                try:
                    await self._callback(origin, up)
                    triggered += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(f"check {up.name} failed: {exc}")
                # tiny pause to avoid hammering Bilibili
                await asyncio.sleep(self._per_request_pause)
        return triggered
