#!/usr/bin/env python3
"""Print TCGplayer listing-related network calls from a real browser session."""

from __future__ import annotations

import asyncio
import os
import sys


PRODUCT_ID = os.environ.get("TCG_DEBUG_PRODUCT_ID", "625277")
CDP_URL = os.environ.get("TCG_BROWSER_CDP_URL", "")


async def main() -> int:
    if not CDP_URL:
        raise RuntimeError("Set TCG_BROWSER_CDP_URL to an Edge/Chrome CDP endpoint")

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def log_response(response):
            url = response.url
            if "mp-search-api.tcgplayer.com" not in url and "mpapi.tcgplayer.com" not in url:
                return
            try:
                text = await response.text()
            except Exception as exc:
                text = f"<body unavailable: {exc}>"
            print(f"\n--- {response.status} {response.request.method} {url}")
            post_data = response.request.post_data
            if post_data:
                print(f"REQUEST {post_data[:1200]}")
            print(f"RESPONSE {text[:2500]}")

        page.on("response", lambda response: asyncio.create_task(log_response(response)))
        await page.goto(f"https://www.tcgplayer.com/product/{PRODUCT_ID}", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        print(f"PAGE {await page.title()} {page.url}")
        for _ in range(6):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(2500)
        await page.wait_for_timeout(10000)
        await browser.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
