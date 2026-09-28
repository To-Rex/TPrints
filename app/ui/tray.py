"""Tizim tray ikonkasi — dastur fonda ishlashi uchun.

Tray tugmalari to'g'ridan-to'g'ri Tkinter'ni chaqirmaydi (thread xavfsizligi):
buyruqlar navbatga yoziladi, UI ularni o'z oqimida bajaradi.
"""
import queue

import pystray
from PIL import Image, ImageDraw

from .. import APP_NAME


def _make_icon_image() -> Image.Image:
    """Oddiy printer belgisi (64x64)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 22, 58, 46], radius=6, fill=(30, 41, 59, 255))
    d.rectangle([16, 8, 48, 24], fill=(148, 163, 184, 255))
    d.rectangle([16, 40, 48, 60], fill=(255, 255, 255, 255))
    d.line([20, 46, 44, 46], fill=(30, 41, 59, 255), width=2)
    d.line([20, 51, 44, 51], fill=(30, 41, 59, 255), width=2)
    d.ellipse([49, 27, 55, 33], fill=(34, 197, 94, 255))
    return img


class Tray:
    def __init__(self):
        self.actions = queue.Queue()   # UI o'qiydigan buyruqlar: show/test/quit
        self._icon = None

    def start(self):
        menu = pystray.Menu(
            pystray.MenuItem("Oynani ko'rsatish",
                             lambda: self.actions.put("show"), default=True),
            pystray.MenuItem("Sinov cheki", lambda: self.actions.put("test")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Chiqish", lambda: self.actions.put("quit")),
        )
        self._icon = pystray.Icon(APP_NAME, _make_icon_image(),
                                  f"{APP_NAME} — chek print xizmati", menu)
        self._icon.run_detached()

    def notify(self, message: str):
        try:
            if self._icon:
                self._icon.notify(message, APP_NAME)
        except Exception:
            pass

    def stop(self):
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass
