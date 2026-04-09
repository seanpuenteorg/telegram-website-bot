"""Capture a screenshot of a deployed website using Playwright."""

import asyncio
from pathlib import Path


async def take_screenshot(url, output_path, width=1440, height=900, wait_seconds=3):
    """Take a screenshot of a URL and save to output_path."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Extra wait for videos/animations to settle
            await asyncio.sleep(wait_seconds)
            await page.screenshot(path=output_path, full_page=False)
        finally:
            await browser.close()

    return output_path


def screenshot_sync(url, output_path, width=1440, height=900):
    """Synchronous wrapper for take_screenshot."""
    return asyncio.run(take_screenshot(url, output_path, width, height))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 screenshotter.py <url> <output.png>")
        sys.exit(1)
    screenshot_sync(sys.argv[1], sys.argv[2])
    print(f"Screenshot saved to {sys.argv[2]}")
