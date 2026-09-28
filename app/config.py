"""Konfiguratsiya: %APPDATA%\\TPrints\\config.json da saqlanadi."""
import json
import os
import threading

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TPrints")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_DIR = os.path.join(APP_DIR, "logs")

DEFAULTS = {
    "host": "127.0.0.1",          # 0.0.0.0 -> tarmoqdagi boshqa kompyuterlar ham yuborishi mumkin
    "port": 9100,
    "api_key": "",                # bo'sh bo'lsa autentifikatsiya talab qilinmaydi
    "default_printer": "",        # bo'sh bo'lsa Windows'dagi asosiy printer
    "start_minimized": False,
    "close_to_tray": True,
    "theme": "dark",              # "dark" (tun) yoki "light" (kun)
    "retries": 2,                 # xatoda qayta urinishlar soni
    "retry_delay": 1.5,
    "history_limit": 200,
    "raster_chunk": 256,          # ESC/POS raster blok balandligi (qator)
    "always_open_drawer": False,  # yoqilsa har bir chekdan keyin pul tortmasi ochiladi
                                  # (printer, rejim va so'rovdagi "drawer" dan qat'i nazar)
    "drawer_printer": "",         # tortma ulangan printer; bo'sh -> chek chiqqan printer
    "printer_profiles": {},       # {printer_name: {mode, paper, dots, cut, feed_lines, drawer}}
}

PROFILE_DEFAULTS = {
    "mode": "escpos",     # "escpos" (termal) yoki "windows" (oddiy printer drayveri)
    "paper": 80,          # 58 yoki 80 mm
    "dots": 0,            # 0 -> paper bo'yicha avtomatik (58->384, 80->576)
    "cut": True,          # chek oxirida kesish
    "feed_lines": 4,      # kesishdan oldin bo'sh qatorlar
    "drawer": False,      # pul tortmasini ochish
}

# Termal printer nomlarini aniqlash uchun kalit so'zlar
THERMAL_HINTS = ("xprinter", "xp-", "xp ", "pos", "therm", "receipt", "chek",
                 "58", "80", "rp-", "rp3", "zj-", "goojprt", "tm-t", "rongta",
                 "gprinter", "sprt", "hoin", "sewoo", "citizen ct")


def paper_dots(profile: dict) -> int:
    """Profil uchun nuqtalardagi kenglik (203dpi)."""
    dots = int(profile.get("dots") or 0)
    if dots > 0:
        return dots
    return 384 if int(profile.get("paper") or 80) == 58 else 576


class Config:
    """Thread-safe konfiguratsiya."""

    def __init__(self):
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        os.makedirs(APP_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)
        self.load()

    def load(self):
        with self._lock:
            try:
                if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    data = dict(DEFAULTS)
                    data.update({k: v for k, v in saved.items() if k in DEFAULTS})
                    self._data = data
            except Exception:
                self._data = dict(DEFAULTS)

    def save(self):
        with self._lock:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value, save=True):
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    def profile(self, printer_name: str) -> dict:
        """Printer profili. Saqlanmagan bo'lsa nomiga qarab taxmin qilinadi."""
        with self._lock:
            profiles = self._data.get("printer_profiles") or {}
            saved = profiles.get(printer_name)
        prof = dict(PROFILE_DEFAULTS)
        if saved:
            prof.update(saved)
            return prof
        low = (printer_name or "").lower()
        if any(h in low for h in THERMAL_HINTS):
            prof["mode"] = "escpos"
            prof["paper"] = 58 if "58" in low else 80
        else:
            prof["mode"] = "windows"
        return prof

    def set_profile(self, printer_name: str, profile: dict):
        with self._lock:
            profiles = dict(self._data.get("printer_profiles") or {})
            clean = {k: profile[k] for k in PROFILE_DEFAULTS if k in profile}
            profiles[printer_name] = clean
            self._data["printer_profiles"] = profiles
            self.save()
