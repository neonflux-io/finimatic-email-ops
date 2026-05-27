from __future__ import annotations

import asyncio


class GroqAdmissionGovernor:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run(self, coro):
        async with self._semaphore:
            return await coro
