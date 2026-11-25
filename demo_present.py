"""Headed, guided live demo of the Wardrobe dashboard.

Prerequisite: demo server on http://127.0.0.1:8899

    python demo_present.py
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8899"
ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "demo_live" / "Inbox"
SHOTS = ROOT / "demo_live" / "shots"


def log(step: str) -> None:
    print(f"[demo] {step}", flush=True)


def shot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)


def wait_job(page, action: str, timeout_ms: int = 120000) -> None:
    page.wait_for_function(
        """async (action) => {
            const r = await fetch('/api/job');
            const j = await r.json();
            return j.action === action && j.state !== 'running';
        }""",
        arg=action,
        timeout=timeout_ms,
    )


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=350,
            args=["--start-maximized", "--window-position=30,20"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(URL, wait_until="networkidle")
        page.bring_to_front()
        page.wait_for_timeout(3000)

        # 0. Landing
        log("Live Chamber landing")
        shot(page, "01-live-chamber")
        page.wait_for_timeout(2500)

        # 1. Scan the disposable demo inbox
        log("Typing demo inbox path")
        page.fill("#scopePathInput", str(INBOX))
        page.wait_for_timeout(1200)
        shot(page, "02-target-set")

        log("Starting Scan & Live Sort")
        page.click("#btnMasterScan", force=True)
        page.wait_for_timeout(4000)
        shot(page, "03-scanning")

        log("Waiting for scan + plan")
        wait_job(page, "plan", timeout_ms=180000)
        page.wait_for_timeout(4500)
        shot(page, "04-plan-ready")

        # 2. Explorer + apply
        log("Opening Explorer")
        page.click('button[data-tab="explorer"]')
        page.wait_for_timeout(2500)
        shot(page, "05-explorer-plan")

        log("Selecting all allowed files and moving them")
        page.click("#btnSelectAllReady", force=True)
        page.wait_for_timeout(800)
        page.click("#btnApplyAllowed", force=True)
        page.wait_for_timeout(2500)
        wait_job(page, "apply", timeout_ms=120000)
        page.wait_for_timeout(3000)
        shot(page, "06-moved")

        # 3. Family vault
        log("Opening Family")
        page.click('button[data-tab="family"]')
        page.wait_for_timeout(2800)
        shot(page, "07-family-plan")
        page.click("#btnFamilyVault", force=True)
        page.wait_for_timeout(2200)
        page.locator(".family-body").scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        shot(page, "08-family-vault")
        log("Opening Aarav folder in the vault explorer")
        page.locator("#familyTree .fam-folder-name", has_text="Aarav").first.click(force=True)
        page.wait_for_timeout(1800)
        page.locator(".family-explorer").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        shot(page, "08b-family-aarav")

        log("Opening Family editor")
        page.click("#btnFamilyEdit", force=True)
        page.wait_for_timeout(2500)
        page.locator("#familyEditor").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        shot(page, "09-family-editor")
        page.click("#btnFamilyClose", force=True)
        page.wait_for_timeout(800)

        # 4. Duplicates
        log("Opening Duplicates")
        page.click('button[data-tab="duplicates"]')
        page.wait_for_timeout(2500)
        page.locator("#dupClustersList").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        shot(page, "10-duplicates")

        # 5. Stats
        log("Opening Stats")
        page.click('button[data-tab="stats"]')
        page.wait_for_timeout(2500)
        shot(page, "11-stats")

        # 6. Changelog
        log("Opening Changelog")
        page.click('button[data-tab="changelog"]')
        page.wait_for_timeout(2500)
        shot(page, "12-changelog")

        # 7. Settings
        log("Opening Settings")
        page.click('button[data-tab="settings"]')
        page.wait_for_timeout(2500)
        page.locator("#settingsBody").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        shot(page, "13-settings")

        # 8. Theme toggle
        log("Toggling theme")
        page.click("#themeBtn", force=True)
        page.wait_for_timeout(1800)
        shot(page, "14-light-theme")
        page.click("#themeBtn", force=True)
        page.wait_for_timeout(1200)

        # 9. Back to live chamber
        log("Back to Live Chamber")
        page.click('button[data-tab="live"]')
        page.wait_for_timeout(3000)
        shot(page, "15-final")

        log("Demo complete - leaving the browser open")
        # Keep the browser visible for the user. The process exits after a pause.
        page.wait_for_timeout(3000)
        # Do not close: returns from main leaves Chromium open until the driver exits.
        time.sleep(2)


if __name__ == "__main__":
    main()
