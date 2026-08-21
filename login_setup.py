import os
import re
import time
from playwright.sync_api import sync_playwright

EVY_PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "EvyAI", "ChromeProfile")


def get_logged_in_email(context):
    try:
        cookies = context.cookies("https://accounts.google.com")
        has_session = any(c["name"] in ("SID", "SAPISID", "SIDCC") for c in cookies)
        if not has_session:
            return None
        page = context.new_page()
        page.goto("https://mail.google.com/mail/u/0/", timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        email = None
        try:
            account = page.locator("a[href*='SignOutOptions'], a[aria-label*='Google Account']").first
            aria = account.get_attribute("aria-label") or account.inner_text(timeout=3000)
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", aria)
            email = m.group(0) if m else None
        except Exception:
            pass
        page.close()
        return email
    except Exception:
        return None


def main():
    print("=" * 50)
    print("  Setup Akun Google untuk Evy")
    print("=" * 50)
    print()
    print("Chrome akan terbuka dengan profil Evy.")
    print("Silakan login dengan AKUN GOOGLE KHUSUS EVY (bukan akun pribadi).")
    print("Setelah login selesai, tutup Chrome untuk menyimpan session.")
    print()

    os.makedirs(EVY_PROFILE_DIR, exist_ok=True)

    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=EVY_PROFILE_DIR,
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

    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://accounts.google.com/")

    print("Menunggu kamu login dan menutup Chrome...")
    print()

    email = None
    last_check = 0
    try:
        while True:
            time.sleep(1)
            if not context.pages:
                break
            now = time.time()
            if email is None and now - last_check >= 3:
                last_check = now
                email = get_logged_in_email(context)
    except KeyboardInterrupt:
        pass

    context.close()
    playwright.stop()

    print()
    print("Session berhasil disimpan!")

    if email:
        print(f"Akun Google aktif: {email}")
        print("Sekarang Evy akan selalu pakai akun ini untuk akses berbagai web.")
    else:
        print("Tidak terdeteksi akun yang login. Pastikan kamu login dengan akun Google Evy ya.")

    input("\nTekan Enter untuk keluar...")
