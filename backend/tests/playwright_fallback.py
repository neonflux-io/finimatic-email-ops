from __future__ import annotations

import asyncio
import os


async def main() -> int:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        print(f"playwright_unavailable:{exc.__class__.__name__}")
        return 2

    app_url = os.getenv("FINIMATIC_APP_URL", "http://127.0.0.1:5173")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(app_url, wait_until="domcontentloaded")
        print(await page.title())
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
