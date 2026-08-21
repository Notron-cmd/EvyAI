import os
import re
import subprocess
import time
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

_EVY_PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "EvyAI", "ChromeProfile")

SITE_ALIASES = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "instagram": "https://www.instagram.com",
    "ig": "https://www.instagram.com",
    "gmail": "https://mail.google.com",
    "email": "https://mail.google.com",
    "google": "https://www.google.com",
    "wikipedia": "https://id.wikipedia.org",
    "wiki": "https://id.wikipedia.org",
    "whatsapp": "https://web.whatsapp.com",
    "wa": "https://web.whatsapp.com",
    "tiktok": "https://www.tiktok.com",
    "facebook": "https://www.facebook.com",
    "fb": "https://www.facebook.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "chatgpt": "https://chatgpt.com",
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "stack overflow": "https://stackoverflow.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "reddit": "https://www.reddit.com",
    "amazon": "https://www.amazon.com",
    "shopee": "https://shopee.co.id",
    "tokopedia": "https://www.tokopedia.com",
    "bukalapak": "https://www.bukalapak.com",
    "lazada": "https://www.lazada.co.id",
    "gojek": "https://www.gojek.com",
    "grab": "https://www.grab.com",
    "detik": "https://www.detik.com",
    "kompas": "https://www.kompas.com",
    "kaskus": "https://www.kaskus.co.id",
    "medium": "https://medium.com",
    "notion": "https://www.notion.so",
    "trello": "https://trello.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "google meet": "https://meet.google.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
}


class BrowserAgent:
    def __init__(self):
        self._playwright = None
        self._context = None
        self._page = None

    def _kill_existing_evy_chrome(self):
        try:
            ps_script = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like '*EvyAI*ChromeProfile*' } | "
                "ForEach-Object { $_.ProcessId }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=20,
            )
            pids = [p for p in result.stdout.split() if p.isdigit()]
            if pids:
                print(f"[Browser] Menutup Chrome Evy lama (profil terkunci): {pids}")
                cmd = ["taskkill", "/F"]
                for pid in pids:
                    cmd += ["/PID", pid]
                subprocess.run(cmd, capture_output=True, timeout=20)
                time.sleep(2)
        except Exception as e:
            print(f"[Browser] Gagal menutup Chrome lama: {e}")

    def _ensure_browser(self):
        if self._context is None:
            os.makedirs(_EVY_PROFILE_DIR, exist_ok=True)
            self._playwright = sync_playwright().start()
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=_EVY_PROFILE_DIR,
                    channel="chrome",
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-infobars",
                    ],
                    ignore_https_errors=True,
                    viewport={"width": 1280, "height": 800},
                )
            except Exception as e:
                print(f"[Browser] Gagal buka Chrome: {e}")
                self._playwright.stop()
                self._playwright = None
                self._kill_existing_evy_chrome()
                self._playwright = sync_playwright().start()
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=_EVY_PROFILE_DIR,
                    channel="chrome",
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-infobars",
                    ],
                    ignore_https_errors=True,
                    viewport={"width": 1280, "height": 800},
                )
            for p in self._context.pages:
                self._apply_anti_detection(p)
            print("[Browser] Chrome Playwright siap (profil Evy).")

    def _apply_anti_detection(self, page):
        try:
            page.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            """)
        except Exception:
            pass

    def _get_page(self):
        self._ensure_browser()
        if self._page is None or self._page.is_closed():
            self._page = self._context.new_page()
            self._apply_anti_detection(self._page)
        return self._page

    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"[Browser] Error: {e}")
            print("[Browser] Coba restart browser...")
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            self._context = None
            self._playwright = None
            self._page = None
            self._ensure_browser()
            return fn(*args, **kwargs)

    def open_url(self, url):
        page = self._safe(self._get_page)
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        print(f"[Browser] Buka: {url}")
        return self.get_state()

    def search_web(self, query):
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        return self.open_url(url)

    def search_youtube(self, query):
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        return self.open_url(url)

    def resolve_and_open(self, name):
        key = name.lower().strip()
        url = SITE_ALIASES.get(key)
        if not url:
            for alias, u in SITE_ALIASES.items():
                if alias in key:
                    url = u
                    break
        if not url:
            if " " in key:
                url = "https://www.google.com/search?q=" + quote_plus(name)
            else:
                url = "https://" + key
        return self.open_url(url)

    def type_text(self, text):
        page = self._get_page()
        typed = False
        selectors = [
            "input[type='search']",
            "input[name='q']",
            "input[placeholder*='cari' i]",
            "input[placeholder*='Cari' i]",
            "input[placeholder*='search' i]",
            "input[placeholder*='Search' i]",
            "input[placeholder*='search YouTube' i]",
            "textarea[placeholder*='search' i]",
            "form[role='search'] input",
        ]
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=1500):
                    locator.click(timeout=1500)
                    locator.fill(text)
                    typed = True
                    break
            except Exception:
                continue
        if not typed:
            try:
                focused = page.evaluate("document.activeElement && document.activeElement.tagName")
                if focused in ("INPUT", "TEXTAREA"):
                    page.keyboard.type(text, delay=60)
                    typed = True
            except Exception:
                pass
        if not typed:
            print("[Browser] Tidak menemukan input untuk mengetik.")
            return self.get_state()
        print(f"[Browser] Ketik: {text}")
        return self.get_state()

    def press_key(self, key):
        page = self._get_page()
        page.keyboard.press(key)
        if key in ("Enter", "Return"):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
        print(f"[Browser] Tekan: {key}")
        return self.get_state()

    def click_first_result(self):
        page = self._get_page()
        try:
            link = page.locator("a:has(h3)").first
            href = link.get_attribute("href")
            if href:
                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                print(f"[Browser] Masuk hasil pertama: {href}")
                return self.get_state()
            link.click(timeout=8000)
            page.wait_for_timeout(2500)
            return self.get_state()
        except Exception as e:
            print(f"[Browser] Gagal klik hasil pertama: {e}")
            return self.get_state()

    def click_text(self, text):
        page = self._get_page()
        escaped = text.replace("'", "\\'")
        attempts = [
            lambda: page.get_by_role("link", name=text, exact=False).first.click(timeout=4000),
            lambda: page.locator(f"a:has-text('{escaped}')").first.click(timeout=4000),
            lambda: page.locator(f"text={escaped}").first.click(timeout=4000),
            lambda: page.get_by_text(text, exact=False).first.click(timeout=4000),
        ]
        clicked = False
        for attempt in attempts:
            try:
                attempt()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            print(f"[Browser] Tidak bisa klik: {text}")
            return self.get_state()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        print(f"[Browser] Klik: {text}")
        return self.get_state()

    def scroll(self, direction="down"):
        page = self._get_page()
        if direction in ("up", "top"):
            page.mouse.wheel(0, -1500)
        else:
            page.mouse.wheel(0, 1500)
        print(f"[Browser] Scroll: {direction}")
        return self.get_state()

    def go_back(self):
        page = self._get_page()
        page.go_back(timeout=15000)
        return self.get_state()

    def go_forward(self):
        page = self._get_page()
        page.go_forward(timeout=15000)
        return self.get_state()

    def get_state(self, max_chars=3000):
        try:
            self._ensure_browser()
            page = self._get_page()
            url = page.url
            title = page.title()
            try:
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                body = ""
            body = " ".join(body.split())
            text = body[:max_chars]
            return {"url": url, "title": title, "text": text}
        except Exception as e:
            return {"url": "", "title": "", "text": "", "error": str(e)}

    def read_content(self):
        return self.get_state(max_chars=6000)

    def verify_google_login(self):
        try:
            self._ensure_browser()
            try:
                cookies = self._context.cookies("https://accounts.google.com")
                has_session = any(c["name"] in ("SID", "SAPISID", "SIDCC") for c in cookies)
            except Exception:
                has_session = False
            if not has_session:
                return False, None
            page = self._get_page()
            page.goto("https://mail.google.com/mail/u/0/", timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            email = None
            try:
                account = page.locator("a[href*='SignOutOptions'], a[aria-label*='Google Account']").first
                aria = account.get_attribute("aria-label") or account.inner_text(timeout=3000)
                import re
                m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", aria)
                email = m.group(0) if m else None
            except Exception:
                pass
            if email:
                return True, email
            return True, None
        except Exception:
            return False, None

    def close(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._context = None
        self._page = None
        print("[Browser] Browser ditutup.")


_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = BrowserAgent()
    return _agent


def search(query):
    return get_agent().search_web(query)


def open_url(url):
    return get_agent().open_url(url)


def verify_google_login():
    return get_agent().verify_google_login()


def close():
    global _agent
    if _agent:
        _agent.close()
    _agent = None