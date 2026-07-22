"""Headless-browser verification of the dashboard UI (Playwright). Not a pytest suite --
the dashboard must already be running (`python -m interfaces.dashboard.app`) and reachable
at DASHBOARD_URL. Run directly:

    python tests/verify_ui.py

Prints PASS/FAIL per step and saves screenshots to tests/screenshots/ for a human to
eyeball. Exits 1 if any step fails.

This host has no sudo, so Chromium's system libs (libnspr4/libnss3/libasound2t64) can't be
apt-installed the normal way (`playwright install --with-deps` needs root). See
_ensure_chromium_libs(): downloads just those .debs with `apt-get download` (fetching a
package doesn't need root, only installing one does) and points LD_LIBRARY_PATH at the
extracted .so files instead. Cached under .cache/chromium-libs/ (gitignored) after the
first run.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).parent.parent
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
LIBS_CACHE = REPO_ROOT / ".cache" / "chromium-libs"
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8500")
ANSWER_TIMEOUT_MS = 90_000

# Missing .so name -> the Ubuntu package that provides it (Ubuntu 24.04 "noble"; adjust if
# `ldd` reports something else on a different distro).
_LIB_TO_PACKAGE = {
    "libnspr4.so": "libnspr4",
    "libnss3.so": "libnss3",
    "libnssutil3.so": "libnss3",
    "libsmime3.so": "libnss3",
    "libasound.so.2": "libasound2t64",
}


def _find_chromium_headless_shell() -> str | None:
    """Locate the cached browser binary WITHOUT starting playwright's Node driver process --
    we need to fix LD_LIBRARY_PATH before that subprocess spawns (and freezes its own copy
    of the environment), not after. `playwright install chromium` downloads to a
    predictable ~/.cache/ms-playwright/chromium_headless_shell-<rev>/... path."""
    cache = Path.home() / ".cache" / "ms-playwright"
    matches = sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
    return str(matches[-1]) if matches else None


def _ensure_chromium_libs(chromium_path: str) -> None:
    """No-op if nothing's missing or this isn't Linux/apt. Otherwise fetches the .debs
    (no root needed to download, only to install) and extracts just the .so files.

    MUST run before `sync_playwright()` is entered: that call spawns a Node.js driver
    subprocess immediately, which captures/freezes its own copy of the environment at
    spawn time -- setting os.environ afterwards (even before .launch()) is too late,
    since the driver (not this Python process) is what execs the browser."""
    try:
        result = subprocess.run(["ldd", chromium_path], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    missing = {line.split()[0] for line in result.stdout.splitlines() if "not found" in line}
    if not missing:
        return

    lib_dir = LIBS_CACHE / "usr" / "lib" / "x86_64-linux-gnu"
    if not (lib_dir.exists() and any(lib_dir.glob("*.so*"))):
        packages = sorted({_LIB_TO_PACKAGE[lib] for lib in missing if lib in _LIB_TO_PACKAGE})
        unknown = missing - set(_LIB_TO_PACKAGE)
        if unknown:
            print(f"warning: missing libs with no known package mapping (may still fail): {unknown}")
        if not packages:
            return
        print(f"Chromium is missing system libs ({', '.join(sorted(missing))}); "
              f"fetching {packages} via apt-get download...")
        deb_dir = LIBS_CACHE / "_debs"
        deb_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["apt-get", "download", *packages], cwd=deb_dir, check=True)
        for deb in deb_dir.glob("*.deb"):
            subprocess.run(["dpkg-deb", "-x", str(deb), str(LIBS_CACHE)], check=True)

    os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}"


def _send(page: Page, question: str) -> None:
    page.fill("#question", question)
    page.click("#send-btn")


def _wait_for_nth_answer_card(page: Page, n: int) -> None:
    page.wait_for_selector(f".turn:nth-of-type({n}) .answer-card", timeout=ANSWER_TIMEOUT_MS)


def step_load(page: Page) -> tuple[bool, str]:
    page.goto(DASHBOARD_URL, wait_until="networkidle")
    page.wait_for_selector("#convo-list", timeout=15_000)
    page.screenshot(path=str(SCREENSHOT_DIR / "01_load.png"))
    title = page.title()
    return "AI Copilot" in title, f"title={title!r}"


def step_new_conversation(page: Page) -> tuple[bool, str]:
    before_id = page.evaluate("currentConversationId")
    page.click("#new-convo-btn")
    page.wait_for_timeout(500)
    after_id = page.evaluate("currentConversationId")
    turns_empty = page.locator("#turns .turn").count() == 0
    sidebar_has_entry = page.locator(f'.convo-item[data-id="{after_id}"]').count() == 1
    ok = bool(after_id) and after_id != before_id and turns_empty and sidebar_has_entry
    return ok, f"before={before_id} after={after_id} turns_empty={turns_empty} sidebar_entry={sidebar_has_entry}"


def step_first_question(page: Page) -> tuple[bool, str]:
    _send(page, "how is the system doing?")
    try:
        _wait_for_nth_answer_card(page, 1)
    except PlaywrightError as e:
        page.screenshot(path=str(SCREENSHOT_DIR / "02_first_answer_TIMEOUT.png"))
        return False, f"answer card never appeared within {ANSWER_TIMEOUT_MS/1000:.0f}s: {e}"

    page.screenshot(path=str(SCREENSHOT_DIR / "02_first_answer.png"))
    answer_text = page.locator(".turn:nth-of-type(1) .answer-text").inner_text()
    has_numbers = bool(re.search(r"\d", answer_text))
    has_card_structure = page.locator(".turn:nth-of-type(1) .answer-card").count() == 1
    return has_numbers and has_card_structure, (
        f"answer_len={len(answer_text)} has_numbers={has_numbers} card_present={has_card_structure}"
    )


def step_followup(page: Page) -> tuple[bool, str]:
    first_still_visible_before = page.locator(".turn:nth-of-type(1) .answer-card").is_visible()
    _send(page, "what about payment?")
    try:
        _wait_for_nth_answer_card(page, 2)
    except PlaywrightError as e:
        page.screenshot(path=str(SCREENSHOT_DIR / "03_followup_TIMEOUT.png"))
        return False, f"second answer card never appeared: {e}"

    page.screenshot(path=str(SCREENSHOT_DIR / "03_followup.png"))
    turn_count = page.locator(".turn").count()
    first_still_visible = page.locator(".turn:nth-of-type(1) .answer-card").is_visible()
    second_text = page.locator(".turn:nth-of-type(2) .answer-text").inner_text()
    has_numbers = bool(re.search(r"\d", second_text))
    ok = turn_count == 2 and first_still_visible_before and first_still_visible and has_numbers
    return ok, f"turn_count={turn_count} first_visible={first_still_visible} second_has_numbers={has_numbers}"


def step_grafana_panels(page: Page, network_log: list[tuple[str, int]]) -> tuple[bool, str]:
    iframes = page.locator("#grafana-panels iframe")
    count = iframes.count()
    if count == 0:
        return False, "no grafana iframes found in #grafana-panels"

    iframes.first.scroll_into_view_if_needed()
    page.wait_for_timeout(3000)  # let iframes finish loading/rendering
    page.screenshot(path=str(SCREENSHOT_DIR / "04_grafana.png"))
    for i in range(count):
        box = iframes.nth(i).bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False, f"iframe {i} has zero size (not rendered)"

    d_solo_responses = [(u, s) for u, s in network_log if "d-solo" in u]
    if not d_solo_responses:
        return False, "no d-solo (grafana panel) network responses observed"
    non_200 = [(u, s) for u, s in d_solo_responses if s != 200]
    if non_200:
        return False, f"non-200 grafana panel responses: {non_200}"

    empty_frames = []
    for frame in page.frames:
        if "d-solo" in frame.url:
            try:
                body_children = frame.locator("body *").count()
            except PlaywrightError:
                body_children = -1  # frame navigated away/detached mid-check
            if body_children == 0:
                empty_frames.append(frame.url)
    if empty_frames:
        return False, f"grafana iframe(s) rendered an empty body: {empty_frames}"

    return True, f"{count} iframes, {len(d_solo_responses)} d-solo responses all 200, all bodies non-empty"


def step_service_panels(page: Page, network_log: list[tuple[str, int]]) -> tuple[bool, str]:
    """Per-service dashboard: select a service, expect 4 metric iframes + 1 larger logs iframe."""
    select = page.locator("#service-select")
    options = select.locator("option").all_text_contents()
    if not options:
        return False, "#service-select has no options"
    target = options[-1]  # not the default-selected first option, to prove the change listener fires
    select.select_option(label=target)

    metric_iframes = page.locator("#service-panels iframe")
    log_iframes = page.locator("#service-logs-panel iframe")
    metric_count = metric_iframes.count()
    log_count = log_iframes.count()
    if metric_count != 4:
        return False, f"expected 4 iframes in #service-panels, found {metric_count}"
    if log_count != 1:
        return False, f"expected 1 iframe in #service-logs-panel, found {log_count}"

    metric_iframes.first.scroll_into_view_if_needed()
    page.wait_for_timeout(3000)
    page.screenshot(path=str(SCREENSHOT_DIR / "05_service_panels.png"))
    log_iframes.first.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)
    page.screenshot(path=str(SCREENSHOT_DIR / "06_service_logs.png"))

    all_iframes = [metric_iframes.nth(i) for i in range(metric_count)] + [log_iframes.nth(i) for i in range(log_count)]
    for i, frame in enumerate(all_iframes):
        box = frame.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False, f"iframe {i} has zero size (not rendered)"
        src = frame.get_attribute("src") or ""
        if f"var-service={target}" not in src:
            return False, f"iframe {i} src missing var-service={target}: {src}"

    log_box = log_iframes.first.bounding_box()
    if not log_box or log_box["height"] <= 300:
        return False, f"logs iframe not bigger than the metric panels: height={log_box}"

    d_solo_responses = [(u, s) for u, s in network_log if "d-solo" in u and f"var-service={target}" in u]
    if not d_solo_responses:
        return False, f"no d-solo responses observed for var-service={target}"
    non_200 = [(u, s) for u, s in d_solo_responses if s != 200]
    if non_200:
        return False, f"non-200 grafana panel responses: {non_200}"

    return True, f"{metric_count} metric + {log_count} logs iframe for '{target}', {len(d_solo_responses)} d-solo responses all 200, logs height={log_box['height']:.0f}"


STEPS = [
    ("1. Load dashboard", step_load),
    ("2. New Conversation clears chat + adds sidebar entry", step_new_conversation),
    ("3. Send question, wait for answer card", step_first_question),
    ("4. Send follow-up, second card appears, first stays visible", step_followup),
    ("5. Grafana iframes present and loaded", step_grafana_panels),
    ("6. Per-service dashboard filters on dropdown selection", step_service_panels),
]
_NEEDS_NETWORK_LOG = {step_grafana_panels, step_service_panels}


def main() -> int:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    exe = _find_chromium_headless_shell()
    if exe:
        _ensure_chromium_libs(exe)
    else:
        print("warning: could not locate cached chromium binary; run `python3 -m playwright install chromium` first")

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        # Attached before any navigation so it also catches the iframe requests fired
        # during the very first page load (step 1), not just ones after step 5 starts.
        network_log: list[tuple[str, int]] = []
        page.on("response", lambda r: network_log.append((r.url, r.status)))

        for name, fn in STEPS:
            try:
                ok, detail = fn(page, network_log) if fn in _NEEDS_NETWORK_LOG else fn(page)
            except Exception as e:
                ok, detail = False, f"EXCEPTION: {e}\n{traceback.format_exc(limit=3)}"
            results.append((name, ok, detail))
            print(f"{'PASS' if ok else 'FAIL'} — {name} :: {detail}")
            if not ok:
                break  # later steps depend on earlier state (conversation, turns)

        browser.close()

    print(f"\nScreenshots: {SCREENSHOT_DIR}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(STEPS)} steps passed" + (f", {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
