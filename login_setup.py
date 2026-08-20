import os
import time
from playwright.sync_api import sync_playwright

EVY_PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "EvyAI", "ChromeProfile")


def main():
    print("=" * 50)
    print("  Setup Akun Google untuk Evy")
    print("=" * 50)
    print()
    print("Chrome akan terbuka dengan profil Evy.")
    print("Silakan login Google seperti biasa.")
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

    try:
        while True:
            time.sleep(1)
            if not context.pages:
                break
    except KeyboardInterrupt:
        pass

    context.close()
    playwright.stop()

    print()
    print("Session berhasil disimpan!")
    print("Sekarang Evy bisa pakai akun Google ini untuk akses berbagai web.")


if __name__ == "__main__":
    main()
