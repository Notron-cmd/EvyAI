import os
import re
import shutil
import subprocess
import threading
import winreg
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import keyboard

try:
    from pycaw.pycaw import AudioUtilities
    _PYCAW_OK = True
except Exception as _pycaw_err:
    _PYCAW_OK = False
    _PYCAW_ERR = _pycaw_err

from browser import SITE_ALIASES

FILE_SEARCH_DIRS = [
    Path(os.environ.get("USERPROFILE", "")) / "Documents",
    Path(os.environ.get("USERPROFILE", "")) / "Downloads",
    Path(os.environ.get("USERPROFILE", "")) / "Desktop",
]

SHORTCUT_DIRS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("USERPROFILE", ""))
    / "Desktop",
    Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    / "Desktop",
]

FILE_SEARCH_RE = re.compile(
    r'^\s*(cari|buka|carikan|bukakan)\s+file\s+(.+?)\s*$',
    re.IGNORECASE,
)

VSCODE_OPEN_RE = re.compile(
    r'^\s*(buka|bukakan)\s+(.+?)\s+(?:di\s+)?(?:visual\s+studio\s+code|visual\s+studio|vscode)\s*$',
    re.IGNORECASE,
)

APP_ALIASES = {
    "vscode": "visual studio code",
    "kode": "visual studio code",
    "word": "microsoft word",
    "excel": "microsoft excel",
    "powerpoint": "microsoft powerpoint",
    "ppt": "microsoft powerpoint",
    "wa": "whatsapp",
    "kalkulator": "calculator",
    "pengaturan": "settings",
    "setelan": "settings",
    "explorer": "file explorer",
    "file manager": "file explorer",
    "paint": "paint",
    "snipping tool": "snipping tool",
}

WEB_FIRST_NAMES = {
    "google", "youtube", "wikipedia", "gmail", "facebook", "instagram",
    "tiktok", "twitter", "github", "netflix", "reddit",
    "shopee", "tokopedia", "detik", "kompas", "medium", "notion",
    "chatgpt", "claude", "gemini", "bing",
}

CRITICAL_PROCESSES = {
    "explorer.exe", "csrss.exe", "lsass.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "smss.exe",
    "dwm.exe", "svchost.exe", "conhost.exe", "system",
}

OPEN_RE = re.compile(
    r'^\s*(tolong\s+)?(buka|bukain|bukakan|jalankan|jalanin|run|launch)\s+(.+?)\s*$',
    re.IGNORECASE,
)
CLOSE_RE = re.compile(
    r'^\s*(tolong\s+)?(tutup|tutupin|tutupan|close|matikan|hentikan)\s+(.+?)\s*$',
    re.IGNORECASE,
)
VOL_SET_RE = re.compile(r'\b(volume|suara)\b', re.IGNORECASE)
VOL_UP_RE = re.compile(
    r'\b(besarkan|naikkan|naikan|keraskan|tingkatkan)\s+(volume|suara)\b'
    r'|\b(volume|suara)\s+(up|naik|lebih besar)\b',
    re.IGNORECASE,
)
VOL_DOWN_RE = re.compile(
    r'\b(kecilkan|turunkan|pelankan|kurangi)\s+(volume|suara)\b'
    r'|\b(volume|suara)\s+(down|turun|lebih kecil)\b',
    re.IGNORECASE,
)
MUTE_RE = re.compile(r'^\s*(mute|bisukan|diamkan)\b', re.IGNORECASE)
MEDIA_PAUSE_RE = re.compile(r'^\s*(pause|jeda|pausekan)\b', re.IGNORECASE)
MEDIA_RESUME_RE = re.compile(r'^\s*(lanjutkan|resume)\b', re.IGNORECASE)
MEDIA_NEXT_RE = re.compile(r'\b(next|selanjutnya)\s*(track|lagu|musik)\b', re.IGNORECASE)
MEDIA_PREV_RE = re.compile(r'\b(prev|previous|sebelumnya)\s*(track|lagu|musik)\b', re.IGNORECASE)

APP_SPLIT_RE = re.compile(r'\s*(?:,|\+|dan|serta|&)\s*', re.IGNORECASE)


_index = None
_index_lock = threading.Lock()


def _normalize(name):
    return re.sub(r'\s+', ' ', name.strip().lower())


def _scan_start_menu():
    result = {}
    for folder in SHORTCUT_DIRS:
        if not folder.exists():
            continue
        for path in folder.rglob("*.lnk"):
            name = path.stem.lower()
            result[name] = str(path)
            if " - " in name:
                stripped = name.split(" - ")[-1]
                if stripped not in result:
                    result[stripped] = str(path)
            clean = name.replace("_", " ").replace("-", " ")
            clean = re.sub(r'\s+', ' ', clean).strip()
            if clean != name and clean not in result:
                result[clean] = str(path)
    return result


def _scan_uwp():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return {}
        import json
        data = json.loads(out.stdout)
        if isinstance(data, dict):
            data = [data]
        result = {}
        for item in data:
            if item.get("Name") and item.get("AppID"):
                result[item["Name"].lower()] = ("uwp", item["AppID"])
        return result
    except Exception as e:
        print(f"[Apps] UWP scan gagal: {e}")
        return {}


def _build_index():
    print("[Apps] Scanning Start Menu...")
    desktop = _scan_start_menu()
    indexed = {name: ("lnk", path) for name, path in desktop.items()}
    print(f"[Apps] Desktop apps: {len(indexed)}")
    uwp = _scan_uwp()
    for name, target in uwp.items():
        if name not in indexed:
            indexed[name] = target
    print(f"[Apps] Total indexed: {len(indexed)} (desktop + UWP)")
    return indexed


def _get_index():
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _build_index()
    return _index


def prewarm_index():
    if _index is not None:
        return
    threading.Thread(target=_get_index, daemon=True).start()


def _resolve_exe(exe_name):
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(
                hive,
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
            )
            val, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)
            if val and Path(val).exists():
                return val
        except OSError:
            continue
    which = shutil.which(exe_name)
    return which


def _resolve_lnk_target(lnk_path):
    try:
        ps = (
            "$s=(New-Object -COM WScript.Shell)"
            f".CreateShortcut('{lnk_path}'); $s.TargetPath"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def find_app(name):
    clean = _normalize(name)
    clean = APP_ALIASES.get(clean, clean)
    index = _get_index()

    if clean in index:
        return clean, index[clean]

    for key, val in index.items():
        if _normalize(key) == clean:
            return key, val

    matches = [
        (key, val) for key, val in index.items()
        if clean in _normalize(key)
    ]
    if len(matches) >= 1:
        matches.sort(key=lambda x: len(x[0]))
        return matches[0]

    for key, val in index.items():
        if _normalize(key) in clean:
            return key, val

    nospace = clean.replace(" ", "")
    if nospace in index:
        return nospace, index[nospace]

    for key in index:
        if _normalize(key).replace(" ", "") == nospace:
            return key, index[key]

    exe_name = f"{clean.split()[0]}.exe"
    resolved = _resolve_exe(exe_name)
    if resolved:
        return clean, ("exe", resolved)
    return None


def open_app(name):
    if _normalize(name) in WEB_FIRST_NAMES:
        return None, name, None
    found = find_app(name)
    if not found:
        return False, name, (
            f"Hmm, aplikasi '{name}' nggak ketemu di laptopmu. "
            f"Sudah terinstall kan?"
        )
    display, target = found
    kind, payload = target
    try:
        if kind == "lnk":
            os.startfile(payload)
        elif kind == "uwp":
            os.startfile(f"shell:AppsFolder\\{payload}")
        elif kind == "exe":
            os.startfile(payload)
        return True, display, f"Oke Notron, aku bukakan {display} ya."
    except Exception as e:
        return False, display, f"Aduh, gagal buka {display}: {e}"


def close_app(name):
    clean = _normalize(name)
    if clean in WEB_FIRST_NAMES:
        return None, name, None
    found = find_app(name)
    if not found:
        return False, name, f"App '{name}' nggak ketemu, jadi nggak bisa aku tutup."
    display, target = found
    kind, payload = target
    exe_path = None
    if kind == "lnk":
        exe_path = _resolve_lnk_target(payload)
    elif kind == "exe":
        exe_path = payload
    if not exe_path:
        return False, display, (
            f"Aku nggak bisa nemu nama proses {display} buat ditutup."
        )
    exe_name = Path(exe_path).name.lower()
    if exe_name in CRITICAL_PROCESSES:
        return False, display, (
            f"{display} adalah proses sistem, nggak boleh aku tutup."
        )
    r = subprocess.run(
        ["taskkill", "/IM", exe_name, "/T"],
        capture_output=True,
    )
    if r.returncode == 0:
        return True, display, f"Oke, {display} aku tutup ya."
    r = subprocess.run(
        ["taskkill", "/IM", exe_name, "/T", "/F"],
        capture_output=True,
    )
    if r.returncode == 0:
        return True, display, f"{display} aku tutup paksa ya."
    return False, display, f"{display} sepertinya tidak sedang jalan."


def _volume(steps, key, msg):
    for _ in range(steps):
        keyboard.press_and_release(key)
    return msg


_vol_iface = None


def _extract_volume(text):
    m = re.search(r'\b(\d{1,3})\s*%?', text)
    if m:
        return int(m.group(1))
    return None


def set_volume(percent):
    if not (0 <= percent <= 100):
        return "Volume maksimal 100 persen ya."
    if not _PYCAW_OK:
        return "Aduh, modul volume nggak tersedia. Coba install ulang pycaw."
    try:
        global _vol_iface
        if _vol_iface is None:
            _vol_iface = AudioUtilities.GetSpeakers().EndpointVolume
        _vol_iface.SetMute(0, None)
        _vol_iface.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"Oke, volume disetel ke {percent} persen."
    except Exception as e:
        return f"Aduh, gagal setel volume: {e}"


def search_files(query, max_results=7):
    results = []
    query_lower = query.lower().strip()
    for folder in FILE_SEARCH_DIRS:
        if not folder.exists():
            continue
        try:
            for path in folder.rglob("*"):
                if len(results) >= max_results:
                    break
                if path.is_file():
                    name = path.stem.lower()
                    if query_lower in name or (len(name) >= 3 and name in query_lower):
                        results.append({
                            "name": path.name,
                            "path": str(path),
                            "folder": path.parent.name,
                        })
        except Exception as e:
            print(f"[FileSearch] Error scanning {folder}: {e}")
        if len(results) >= max_results:
            break
    return results[:max_results]


def open_file(path):
    try:
        os.startfile(path)
        return True, f"Oke, membuka {Path(path).name}"
    except Exception as e:
        return False, f"Gagal membuka: {e}"


_JUNK_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "env",
    ".next", "dist", "build", "site-packages", ".gradle", "vendor",
}


def _norm_name(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def search_folders(query, max_results=7):
    query_norm = _norm_name(query)
    if not query_norm:
        return []
    results = []
    for root_dir in FILE_SEARCH_DIRS:
        if not root_dir.exists():
            continue
        try:
            for current, dirs, _files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d.lower() not in _JUNK_DIRS and not d.startswith(".")]
                for d in dirs:
                    name_norm = _norm_name(d)
                    if not name_norm:
                        continue
                    if len(query_norm) >= 3:
                        matched = query_norm in name_norm or (
                            len(name_norm) >= 3 and name_norm in query_norm
                        )
                    else:
                        matched = name_norm == query_norm
                    if matched:
                        full = Path(current) / d
                        results.append({
                            "name": d,
                            "path": str(full),
                            "folder": Path(current).name,
                            "depth": len(full.parts),
                        })
        except Exception as e:
            print(f"[FolderSearch] Error scanning {root_dir}: {e}")
    results.sort(key=lambda r: r["depth"])
    return results[:max_results]


_VSCODE_CMD = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Microsoft VS Code", "bin", "code.cmd"
)


def open_in_vscode(folder_path):
    try:
        subprocess.run(f'"{_VSCODE_CMD}" "{folder_path}"', shell=True, check=True, capture_output=True)
        return True, f"Oke, membuka {Path(folder_path).name} di VS Code"
    except Exception as e:
        return False, f"Gagal membuka di VS Code: {e}"


_STT_CORRECTIONS = {
    "puka": "buka",
    "pukain": "bukain",
    "pukakan": "bukakan",
    "tutupn": "tutupin",
}


def _normalize_stt(text):
    words = text.split()
    if words:
        first = words[0].lower()
        if first in _STT_CORRECTIONS:
            words[0] = _STT_CORRECTIONS[first]
    return " ".join(words)


def _split_app_names(remainder):
    parts = [p.strip() for p in APP_SPLIT_RE.split(remainder)]
    parts = [p for p in parts if p]
    return parts if len(parts) > 1 else None


def _open_one(name):
    clean = _normalize(name)
    if clean in WEB_FIRST_NAMES:
        url = SITE_ALIASES.get(clean) or SITE_ALIASES.get(clean.split()[0])
        if url:
            try:
                os.startfile(url)
                return True, name, "web"
            except Exception as e:
                return False, name, f"err: {e}"
        return False, name, "err: URL tidak ditemukan"
    ok, display, msg = open_app(name)
    if ok is True:
        return True, display, "app"
    if ok is None or ok is False:
        url = SITE_ALIASES.get(clean) or SITE_ALIASES.get(clean.split()[0])
        if url:
            try:
                os.startfile(url)
                return True, name + " Web", "web-fallback"
            except Exception as e:
                return False, name, f"err: web fallback gagal: {e}"
    return False, display if ok is not None else name, f"err: {msg}"


def _open_multiple(app_names):
    with ThreadPoolExecutor(max_workers=len(app_names)) as ex:
        futures = {ex.submit(_open_one, n): n for n in app_names}
        results = {futures[f]: f.result() for f in as_completed(futures)}
    success = [(n, d, k) for n, (ok, d, k) in results.items() if ok]
    errors = [(n, k) for n, (ok, d, k) in results.items() if not ok]
    if not success:
        return "Aduh, nggak ada yang berhasil aku buka. " + "; ".join([f"{n}: {k}" for n, k in errors])
    msg = "Oke, aku bukakan " + " dan ".join([d for n, d, k in success]) + "."
    if errors:
        msg += " Tapi " + " dan ".join([f"{n} gagal" for n, k in errors]) + "."
    return msg


def handle_command(text):
    text = _normalize_stt(text)
    if MUTE_RE.search(text):
        keyboard.press_and_release("volume mute")
        return "Oke, suara aku mute."

    if VOL_SET_RE.search(text):
        n = _extract_volume(text)
        if n is not None:
            return set_volume(n)

    if VOL_UP_RE.search(text):
        return _volume(3, "volume up", "Oke, volume aku naikkan.")

    if VOL_DOWN_RE.search(text):
        return _volume(3, "volume down", "Oke, volume aku turunkan.")

    if MEDIA_PAUSE_RE.search(text):
        keyboard.press_and_release("play/pause media")
        return "Oke, musik aku jeda dulu."

    if MEDIA_RESUME_RE.search(text):
        keyboard.press_and_release("play/pause media")
        return "Oke, aku lanjutkan musiknya."

    if MEDIA_NEXT_RE.search(text):
        keyboard.press_and_release("next track")
        return "Oke, lagu berikutnya ya."

    if MEDIA_PREV_RE.search(text):
        keyboard.press_and_release("previous track")
        return "Oke, lagu sebelumnya ya."

    m = VSCODE_OPEN_RE.match(text)
    if m:
        query = m.group(2).strip()
        query = re.sub(r'^folder\s+', '', query, flags=re.IGNORECASE).strip()
        results = search_folders(query, max_results=5)
        if not results:
            return f"Folder '{query}' nggak ketemu di Documents, Downloads, atau Desktop."
        first = results[0]
        ok, msg = open_in_vscode(first["path"])
        if ok:
            return f"Oke, membuka {first['name']} di VS Code"
        return msg

    m = FILE_SEARCH_RE.match(text)
    if m:
        action = m.group(1).lower()
        query = m.group(2).strip()
        results = search_files(query, max_results=7)
        if not results:
            return f"File '{query}' nggak ketemu di Documents, Downloads, atau Desktop."
        if action in ("buka", "bukakan"):
            first = results[0]
            ok, msg = open_file(first["path"])
            if ok:
                return f"Oke, membuka {first['name']} di folder {first['folder']}"
            return msg
        lines = [f"{i+1}. {r['name']} ({r['folder']})" for i, r in enumerate(results)]
        return f"Ketemu {len(results)} file:\n" + "\n".join(lines)

    m = OPEN_RE.match(text)
    if m:
        remainder = m.group(3).strip()
        apps = _split_app_names(remainder)
        if apps:
            return _open_multiple(apps)
        app_name = remainder
        ok, display, msg = open_app(app_name)
        if ok is True:
            return msg
        if ok is None:
            return None
        clean = _normalize(app_name)
        url = SITE_ALIASES.get(clean) or SITE_ALIASES.get(clean.split()[0])
        if url:
            try:
                os.startfile(url)
                return f"Oke, aku bukakan {app_name} di browser."
            except Exception as e:
                return f"Aduh, gagal buka {app_name} di browser: {e}"
        return msg
        return msg

    m = CLOSE_RE.match(text)
    if m:
        app_name = m.group(3).strip()
        ok, display, msg = close_app(app_name)
        if ok is None:
            return None
        return msg

    return None
