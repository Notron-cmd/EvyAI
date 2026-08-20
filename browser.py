import os
from pathlib import Path
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

_playwright = None
_context = None

_EVY_PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "EvyAI", "ChromeProfile")


def _ensure_browser():
    global _playwright, _context
    if _context is None:
        os.makedirs(_EVY_PROFILE_DIR, exist_ok=True)
        _playwright = sync_playwright().start()
        _context = _playwright.chromium.launch_persistent_context(
            user_data_dir=_EVY_PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 800},
        )
        for page in _context.pages:
            page.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            """)
        print("[Browser] Chrome Playwright siap (profil Evy).")


def search(query):
    global _context, _playwright
    
    try:
        _ensure_browser()
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        page = _context.new_page()
        page.evaluate("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """)
        page.goto(search_url, timeout=15000)
        print(f"[Browser] Cari di Google: {query}")
    except Exception as e:
        print(f"[Browser] Error: {e}")
        print("[Browser] Coba restart browser...")
        try:
            if _context:
                _context.close()
        except:
            pass
        try:
            if _playwright:
                _playwright.stop()
        except:
            pass
        _context = None
        _playwright = None
        
        try:
            _ensure_browser()
            search_url = f"https://www.google.com/search?q={quote_plus(query)}"
            page = _context.new_page()
            page.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            """)
            page.goto(search_url, timeout=15000)
            print(f"[Browser] Cari di Google (retry): {query}")
        except Exception as e2:
            print(f"[Browser] Error setelah restart: {e2}")


def close():
    global _playwright, _context
    if _context:
        _context.close()
        _playwright.stop()
        _playwright = None
        _context = None
        print("[Browser] Browser ditutup.")
