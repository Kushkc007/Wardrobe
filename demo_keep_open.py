"""Open the demo dashboard in a visible browser and keep it open."""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        slow_mo=250,
        args=["--start-maximized", "--window-position=30,20"],
    )
    ctx = browser.new_context(no_viewport=True)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8899", wait_until="networkidle")
    page.bring_to_front()
    page.wait_for_timeout(1500)
    page.click('button[data-tab="family"]')
    page.wait_for_timeout(1200)
    page.click("#btnFamilyVault", force=True)
    page.wait_for_timeout(1500)
    try:
        page.locator("#familyTree .fam-folder-name", has_text="Aarav").first.click(force=True)
        page.wait_for_timeout(900)
        page.locator("#familyListing .fam-row-folder", has_text="Resume").first.click(force=True)
        page.wait_for_timeout(900)
        page.locator(".family-explorer").scroll_into_view_if_needed()
    except Exception:
        pass
    time.sleep(3600)
