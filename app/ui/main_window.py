"""Asosiy oyna — zamonaviy, minimalistik, animatsiyali UI (CustomTkinter).

Kun (light) va Tun (dark) mavzulari; barcha ranglar (kun, tun) juftlik
sifatida berilgan — mavzu almashganda butun interfeys avtomatik yangilanadi.

Animatsiyalar:
  - yon panelda faol bo'limga sirg'alib boruvchi indikator
  - sahifalarning yo'nalishga qarab silliq siljishi
  - radar uslubida tarqaluvchi server holati pulsi
  - printer kartochkalarining kaskadli paydo bo'lishi
  - statistika raqamlarining sanab o'sishi
  - yangi vazifaning yaltirab ajralishi
  - toast bildirishnomalar (pastdan suzib chiqadi)
  - chop etish paytida jonli progress chiziq
  - oynaning silliq paydo bo'lishi, xabarlarning so'nishi
"""
import os
import sys
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import ImageTk

from .. import APP_NAME, APP_VERSION
from ..config import PROFILE_DEFAULTS, paper_dots
from ..logger import tail_logs
from ..printing import win_printer

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ---------- rang palitrasi: (kun, tun) ----------
BG = ("#eef1f7", "#0d1117")
SIDEBAR = ("#ffffff", "#0a0e14")
CARD = ("#ffffff", "#161b26")
CARD_HOVER = ("#f1f5f9", "#1c2330")
BORDER = ("#dde3ec", "#232b3a")
CHIP = ("#eef2f7", "#0d1117")
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_HOVER = ("#1d4ed8", "#2563eb")
ACCENT_SOFT = ("#dbeafe", "#12233f")
GREEN = ("#16a34a", "#22c55e")
RED = ("#dc2626", "#ef4444")
AMBER = ("#d97706", "#f59e0b")
TEXT = ("#111827", "#e6e9ef")
MUTED = ("#5b6472", "#8b93a3")

STATUS_COLORS = {"tayyor": GREEN, "xato": RED,
                 "chiqarilmoqda": AMBER, "navbatda": MUTED}
VIEW_ORDER = ["printers", "jobs", "settings", "logs"]
DRAWER_ANY = "(chek printeri)"   # tortma: chek qaysi printerga chiqsa, o'shanga


def col(pair) -> str:
    """Joriy mavzuga mos rangni qaytaradi."""
    return pair[0] if ctk.get_appearance_mode() == "Light" else pair[1]


def _blend(c1: str, c2: str, t: float) -> str:
    """Ikki hex rang orasida silliq o'tish (0..1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _set_titlebar(window, dark: bool):
    """Windows sarlavha panelini mavzuga moslash."""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), 4)
    except Exception:
        pass


# ---------- Windows autostart ----------

def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    script = os.path.abspath(sys.argv[0])
    return f'"{pyw}" "{script}" --minimized'


def get_autostart() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


class MainWindow:
    def __init__(self, config, job_queue, manager, tray, server, logger):
        self.config = config
        self.jobs = job_queue
        self.manager = manager
        self.tray = tray
        self.server = server
        self.logger = logger
        self._quitting = False
        self._tray_hint_shown = False
        self._sel_printer = None
        self._printer_cards = {}
        self._entrance_afters = []
        self._job_rows = []
        self._jobs_sig = None
        self._known_job_ids = set()
        self._log_sig = None
        self._current_view = None
        self._ping_t = 0.0
        self._stat_prev = {}
        self._busy_shown = False
        self._toast_frame = None
        self._nav_ind_y = None
        self._lan_ip_cache = None
        self._lan_ip_time = 0.0

        theme = self.config.get("theme") or "dark"
        ctk.set_appearance_mode("dark" if theme == "dark" else "light")

        self.root = ctk.CTk(fg_color=BG)
        self.root.title(f"{APP_NAME} — chek print xizmati")
        # Kichik ekranlarda (POS monitorlar) oyna ekrandan chiqib ketmasin:
        # standart 1040x680 (min 900x580), ekran kichik bo'lsa unga moslanadi.
        try:
            scale = float(ctk.ScalingTracker.get_window_scaling(self.root)) or 1.0
            sw = self.root.winfo_screenwidth() / scale
            sh = self.root.winfo_screenheight() / scale
        except Exception:
            sw, sh = 1920, 1080
        w = int(min(1040, max(640, sw - 40)))
        h = int(min(680, max(460, sh - 90)))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(min(900, w), min(580, h))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        _set_titlebar(self.root, theme == "dark")

        self.F = lambda s, w="normal": ctk.CTkFont("Segoe UI", s, w)
        self.MONO = ctk.CTkFont("Consolas", 12)

        self._build_layout()
        self._build_printers_view()
        self._build_jobs_view()
        self._build_settings_view()
        self._build_logs_view()

        self.show_view("printers", animate=False)
        self.refresh_printers()

        self.root.after(200, lambda: self._move_nav_indicator(
            self._current_view, animate=False))
        self.root.after(300, self._poll_tray)
        self.root.after(700, self._poll_data)
        self.root.after(60, self._ping)

    def _is_dark(self) -> bool:
        return ctk.get_appearance_mode() != "Light"

    # ================= umumiy tuzilma =================

    def _build_layout(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # ---- yon panel ----
        side = ctk.CTkFrame(self.root, width=214, corner_radius=0,
                            fg_color=SIDEBAR)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        self._side = side

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(20, 24))
        badge = ctk.CTkFrame(logo, width=44, height=44, corner_radius=13,
                             fg_color=ACCENT_SOFT)
        badge.pack(side="left")
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="🖨", font=self.F(20)).place(relx=0.5,
                                                              rely=0.5,
                                                              anchor="center")
        box = ctk.CTkFrame(logo, fg_color="transparent")
        box.pack(side="left", padx=10)
        ctk.CTkLabel(box, text=APP_NAME, font=self.F(19, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(box, text="chek print xizmati", font=self.F(11),
                     text_color=MUTED).pack(anchor="w")

        # faol bo'limga sirg'alib boruvchi indikator
        self.nav_indicator = ctk.CTkFrame(side, width=4, height=26,
                                          corner_radius=2, fg_color=ACCENT)
        self.nav_indicator.place(x=5, y=-60)

        self._nav_buttons = {}
        nav_items = [("printers", "🖨   Printerlar"),
                     ("jobs", "🧾   Vazifalar"),
                     ("settings", "⚙   Sozlamalar"),
                     ("logs", "📋   Jurnal")]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                side, text=label, anchor="w", height=42, corner_radius=10,
                font=self.F(14), fg_color="transparent", text_color=MUTED,
                hover_color=CARD_HOVER,
                command=lambda k=key: self.show_view(k))
            btn.pack(fill="x", padx=14, pady=3)
            self._nav_buttons[key] = btn

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=14)

        self.theme_seg = ctk.CTkSegmentedButton(
            bottom, values=["☀  Kun", "🌙  Tun"], height=32,
            corner_radius=9, font=self.F(12),
            fg_color=CHIP, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=CHIP, unselected_hover_color=CARD_HOVER,
            command=self._on_theme)
        self.theme_seg.set("🌙  Tun" if self._is_dark() else "☀  Kun")
        self.theme_seg.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(bottom, text="Trayga yashirish", height=36,
                      corner_radius=10, font=self.F(13),
                      fg_color=CARD, hover_color=CARD_HOVER,
                      text_color=MUTED, border_width=1, border_color=BORDER,
                      command=self.hide).pack(fill="x")
        ctk.CTkButton(bottom, text="✕  Ishni yakunlash", height=36,
                      corner_radius=10, font=self.F(13),
                      fg_color="transparent",
                      hover_color=("#fee2e2", "#2a1215"),
                      text_color=RED, border_width=1, border_color=RED,
                      command=self.confirm_quit).pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(bottom, text=f"v{APP_VERSION}", font=self.F(11),
                     text_color=MUTED).pack(pady=(8, 0))

        # ---- o'ng qism ----
        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=18, pady=16)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(right, height=60, corner_radius=14,
                              fg_color=CARD, border_width=1,
                              border_color=BORDER)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        # radar-puls holat indikatori
        self.ping_canvas = tk.Canvas(header, width=28, height=28,
                                     highlightthickness=0, bd=0,
                                     bg=col(CARD))
        self.ping_canvas.grid(row=0, column=0, padx=(16, 6), pady=16)

        stat_box = ctk.CTkFrame(header, fg_color="transparent")
        stat_box.grid(row=0, column=1, sticky="w", pady=8)
        self.status_label = ctk.CTkLabel(stat_box, text="...", anchor="w",
                                         font=self.F(13, "bold"),
                                         text_color=TEXT)
        self.status_label.pack(anchor="w")
        self.url_label = ctk.CTkLabel(stat_box, text="", anchor="w",
                                      font=self.F(11), text_color=MUTED,
                                      cursor="hand2")
        self.url_label.pack(anchor="w")
        self.url_label.bind("<Button-1>", self._copy_url)

        ctk.CTkButton(header, text="Sinov cheki", height=34, corner_radius=9,
                      font=self.F(13), fg_color=ACCENT, text_color="white",
                      hover_color=ACCENT_HOVER,
                      command=self.print_test).grid(row=0, column=2,
                                                    padx=(6, 14))
        self._update_status_label()

        # chop etish paytida jonli chiziq (bekor holatda ko'rinmaydi)
        self.progress = ctk.CTkProgressBar(right, height=4, corner_radius=2,
                                           fg_color=BG, progress_color=BG)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.progress.configure(mode="indeterminate",
                                indeterminate_speed=1.2)
        self.progress.set(0)

        self.content = ctk.CTkFrame(right, fg_color="transparent")
        self.content.grid(row=2, column=0, sticky="nsew", pady=(10, 0))

        self._views = {}
        for key in VIEW_ORDER:
            self._views[key] = ctk.CTkFrame(self.content,
                                            fg_color="transparent")

    def _title_block(self, parent, title, subtitle):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(box, text=title, font=self.F(21, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(box, text=subtitle, font=self.F(11),
                     text_color=MUTED).pack(anchor="w")
        return box

    def _on_theme(self, value: str):
        dark = "Tun" in value
        ctk.set_appearance_mode("dark" if dark else "light")
        self.config.set("theme", "dark" if dark else "light")
        _set_titlebar(self.root, dark)
        try:
            self.ping_canvas.configure(bg=col(CARD))
        except Exception:
            pass
        self._log_sig = None          # jurnal ranglarini yangilash uchun
        self._refresh_logs()
        self.logger.info("Mavzu: %s", "tun" if dark else "kun")

    def _copy_url(self, _e=None):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._url_text)
            self._toast("📋 Manzil nusxalandi")
        except Exception:
            pass

    def _get_lan_ip(self) -> str:
        """Kompyuterning lokal tarmoqdagi IP manzili (30s keshlanadi)."""
        import socket
        import time
        now = time.time()
        if self._lan_ip_cache and now - self._lan_ip_time < 30:
            return self._lan_ip_cache
        ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))   # trafik yuborilmaydi
                ip = s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                pass
        self._lan_ip_cache = ip
        self._lan_ip_time = now
        return ip

    def _update_status_label(self):
        host = self.config.get("host")
        port = self.config.get("port")
        if self.server and self.server.error:
            self._status_ok = False
            self.status_label.configure(text="Server xatosi")
            self.url_label.configure(text=str(self.server.error)[:70])
            self._url_text = ""
        else:
            self._status_ok = True
            if host in ("0.0.0.0", ""):
                # tarmoq rejimi — boshqa qurilmalar shu IP ga ulanadi
                lan = self._get_lan_ip()
                self._url_text = f"http://{lan}:{port}"
                hint = "tarmoq IP · nusxalash uchun bosing"
            else:
                self._url_text = f"http://{host}:{port}"
                hint = "nusxalash uchun bosing"
            self.status_label.configure(text="Server ishlamoqda")
            self.url_label.configure(text=f"{self._url_text}   ({hint})")

    # ---------- animatsiyalar ----------

    def _ping(self):
        """Radar uslubidagi tarqaluvchi holat pulsi."""
        if self._quitting:
            return
        c = self.ping_canvas
        try:
            c.delete("all")
            cx = cy = 14
            if not getattr(self, "_status_ok", True):
                c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                              fill=col(RED), outline="")
            else:
                t = self._ping_t
                r = 5 + 8 * t
                ring = _blend(col(GREEN), col(CARD), t * t)
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=ring, width=2)
                c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                              fill=col(GREEN), outline="")
                self._ping_t = (self._ping_t + 0.035) % 1.0
        except Exception:
            pass
        self.root.after(45, self._ping)

    def _move_nav_indicator(self, key: str, animate: bool = True):
        """Indikatorning faol tugma yoniga sirg'alishi."""
        btn = self._nav_buttons.get(key)
        if not btn:
            return
        try:
            self.root.update_idletasks()
            target = btn.winfo_y() + (btn.winfo_height() - 26) // 2
        except Exception:
            return
        if not animate or self._nav_ind_y is None:
            self._nav_ind_y = target
            self.nav_indicator.place(x=5, y=target)
            return
        start = self._nav_ind_y
        self._nav_ind_y = target
        steps = 9
        def step(i=0):
            if self._quitting:
                return
            if i > steps:
                self.nav_indicator.place(x=5, y=target)
                return
            t = i / steps
            ease = 1 - (1 - t) ** 3
            self.nav_indicator.place(x=5, y=round(start + (target - start) * ease))
            self.root.after(14, lambda: step(i + 1))
        step()

    def show_view(self, key: str, animate: bool = True):
        if key == self._current_view:
            return
        for k, btn in self._nav_buttons.items():
            active = k == key
            btn.configure(fg_color=ACCENT_SOFT if active else "transparent",
                          text_color=TEXT if active else MUTED)
        self._move_nav_indicator(key, animate=animate)

        old = self._views.get(self._current_view)
        # yo'nalish: pastga o'tsak o'ngdan, tepaga o'tsak chapdan
        direction = 1
        if self._current_view in VIEW_ORDER:
            direction = (1 if VIEW_ORDER.index(key) >
                         VIEW_ORDER.index(self._current_view) else -1)
        new = self._views[key]
        self._current_view = key
        new.lift()
        if not animate:
            if old is not None:
                old.place_forget()
            new.place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        offset = 0.05 * direction
        steps = 9
        def step(i=0):
            if self._quitting:
                return
            if i > steps:
                if old is not None and old is not new:
                    old.place_forget()
                new.place(relx=0, rely=0, relwidth=1, relheight=1)
                return
            t = i / steps
            ease = 1 - (1 - t) ** 3
            new.place(relx=offset * (1 - ease), rely=0,
                      relwidth=1, relheight=1)
            self.root.after(13, lambda: step(i + 1))
        step()

    def _fade_in(self):
        """Oynaning silliq paydo bo'lishi."""
        try:
            self.root.attributes("-alpha", 0.0)
            def step(i=0):
                if self._quitting or i > 10:
                    self.root.attributes("-alpha", 1.0)
                    return
                self.root.attributes("-alpha", i / 10)
                self.root.after(18, lambda: step(i + 1))
            step()
        except Exception:
            pass

    def _toast(self, text: str, color=None):
        """Pastdan suzib chiquvchi qisqa bildirishnoma."""
        if self._toast_frame is not None:
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
        f = ctk.CTkFrame(self.root, corner_radius=10, fg_color=CARD,
                         border_width=1, border_color=BORDER)
        ctk.CTkLabel(f, text=text, font=self.F(12, "bold"),
                     text_color=color or TEXT).pack(padx=16, pady=9)
        self._toast_frame = f
        start_y, end_y = 1.06, 0.975
        steps = 8

        def slide_in(i=0):
            if self._quitting or not f.winfo_exists():
                return
            if i > steps:
                f.place(relx=0.985, rely=end_y, anchor="se")
                self.root.after(2300, slide_out)
                return
            t = i / steps
            ease = 1 - (1 - t) ** 3
            f.place(relx=0.985, rely=start_y + (end_y - start_y) * ease,
                    anchor="se")
            self.root.after(16, lambda: slide_in(i + 1))

        def slide_out(i=0):
            if self._quitting or not f.winfo_exists():
                return
            if i > steps:
                f.destroy()
                return
            t = i / steps
            f.place(relx=0.985, rely=end_y + (start_y - end_y) * (t * t),
                    anchor="se")
            self.root.after(16, lambda: slide_out(i + 1))

        slide_in()

    def _flash_note(self, label: ctk.CTkLabel, text: str, color=GREEN):
        """Xabarni ko'rsatib, 3 soniyadan keyin asta so'ndirish."""
        label.configure(text=text, text_color=color)
        def fade(i=0):
            if self._quitting or i > 12:
                label.configure(text="")
                return
            label.configure(text_color=_blend(col(color), col(CARD), i / 12))
            self.root.after(70, lambda: fade(i + 1))
        self.root.after(2600, fade)

    def _animate_number(self, label: ctk.CTkLabel, old: int, new: int):
        """Statistika raqamining sanab o'sishi."""
        if old == new:
            return
        steps = 8
        def step(i=0):
            if self._quitting:
                return
            if i > steps:
                label.configure(text=str(new))
                return
            t = 1 - (1 - i / steps) ** 2
            label.configure(text=str(round(old + (new - old) * t)))
            self.root.after(32, lambda: step(i + 1))
        step()

    def _flash_row(self, row: ctk.CTkFrame):
        """Yangi vazifa qatorini urg'u rangi bilan yaltiratish."""
        try:
            row.configure(border_color=ACCENT)
        except Exception:
            return
        def fade(i=0):
            if self._quitting:
                return
            try:
                if not row.winfo_exists():
                    return
                if i > 8:
                    row.configure(border_color=BORDER)
                    return
                row.configure(border_color=_blend(col(ACCENT), col(BORDER),
                                                  i / 8))
            except Exception:
                return
            self.root.after(70, lambda: fade(i + 1))
        self.root.after(500, fade)

    def _set_busy(self, busy: bool):
        """Chop etish paytida jonli chiziqni yoqish/o'chirish."""
        if busy == self._busy_shown:
            return
        self._busy_shown = busy
        try:
            if busy:
                self.progress.configure(progress_color=ACCENT)
                self.progress.start()
            else:
                self.progress.stop()
                self.progress.configure(progress_color=BG)
                self.progress.set(0)
        except Exception:
            pass

    # ================= Printerlar =================

    def _build_printers_view(self):
        v = self._views["printers"]

        toolbar = ctk.CTkFrame(v, fg_color="transparent")
        toolbar.pack(fill="x")
        self._title_block(toolbar, "Printerlar",
                          "Ulangan printerlar va ularning profillari").pack(
            side="left")

        def tb_btn(text, cmd, primary=False):
            return ctk.CTkButton(
                toolbar, text=text, height=32, corner_radius=9,
                font=self.F(12),
                fg_color=ACCENT if primary else CARD,
                hover_color=ACCENT_HOVER if primary else CARD_HOVER,
                text_color="white" if primary else TEXT,
                border_width=0 if primary else 1, border_color=BORDER,
                command=cmd)

        tb_btn("Ko'rib chiqish", self.show_preview).pack(side="right", padx=3)
        tb_btn("Profil", self.edit_profile).pack(side="right", padx=3)
        tb_btn("Standart qilish", self.make_default).pack(side="right", padx=3)
        tb_btn("⟳ Yangilash", self.refresh_printers).pack(side="right", padx=3)

        self.printers_area = ctk.CTkScrollableFrame(
            v, fg_color="transparent", scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED)
        self.printers_area.pack(fill="both", expand=True, pady=(12, 0))

    def refresh_printers(self):
        try:
            printers = win_printer.list_printers()
        except Exception as e:
            self.logger.error("Printerlarni o'qib bo'lmadi: %s", e)
            printers = []
        self._printers = printers
        names = {p["name"] for p in printers}
        if self._sel_printer not in names:
            self._sel_printer = None
        menu = getattr(self, "drawer_printer_menu", None)
        if menu is not None:
            try:
                cur = menu.get()
                menu.configure(values=self._drawer_printer_values())
                menu.set(cur)
            except Exception:
                pass

        for aid in self._entrance_afters:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._entrance_afters = []
        for card in self._printer_cards.values():
            card.destroy()
        self._printer_cards = {}

        app_default = self.config.get("default_printer") or ""
        for i, p in enumerate(printers):
            card = self._make_printer_card(p, app_default)
            self._printer_cards[p["name"]] = card
            # kaskadli paydo bo'lish
            aid = self.root.after(
                i * 45,
                lambda c=card: c.pack(fill="x", pady=5, padx=2)
                if c.winfo_exists() else None)
            self._entrance_afters.append(aid)

    def _drawer_printer_values(self) -> list:
        """Sozlamalardagi «Tortma ulangan printer» menyusi uchun ro'yxat."""
        names = [p["name"] for p in (getattr(self, "_printers", None) or [])]
        if not names:
            try:
                names = [p["name"] for p in win_printer.list_printers()]
            except Exception:
                names = []
        saved = (self.config.get("drawer_printer") or "").strip()
        if saved and saved not in names:
            names.append(saved)
        return [DRAWER_ANY] + names

    def _make_printer_card(self, p: dict, app_default: str):
        name = p["name"]
        prof = self.config.profile(name)
        selected = name == self._sel_printer
        is_thermal = prof["mode"] == "escpos"
        card = ctk.CTkFrame(self.printers_area, corner_radius=12,
                            fg_color=CARD, border_width=1,
                            border_color=ACCENT if selected else BORDER)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        inner.grid_columnconfigure(1, weight=1)

        icon = ctk.CTkFrame(inner, width=42, height=42, corner_radius=11,
                            fg_color=ACCENT_SOFT if is_thermal else CHIP)
        icon.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        icon.grid_propagate(False)
        ctk.CTkLabel(icon, text="🧾" if is_thermal else "🖨",
                     font=self.F(17)).place(relx=0.5, rely=0.5,
                                            anchor="center")

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(top, text=name, font=self.F(15, "bold"),
                     text_color=TEXT).pack(side="left")
        is_default = (name == app_default) if app_default else p["default"]
        if is_default:
            ctk.CTkLabel(top, text="  standart  ", font=self.F(11, "bold"),
                         corner_radius=6, fg_color=ACCENT_SOFT,
                         text_color=ACCENT).pack(side="left", padx=10)

        ok = p["status"] == "tayyor"
        ctk.CTkLabel(top, text=("● " + p["status"]), font=self.F(12),
                     text_color=GREEN if ok else AMBER).pack(side="right")

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        mode = "Termal · ESC/POS" if is_thermal else "Windows drayveri"
        chips = [mode]
        if is_thermal:
            chips.append(f'{prof["paper"]}mm · {paper_dots(prof)}px')
            if prof.get("cut", True):
                chips.append("kesish")
        drawer_printer = (self.config.get("drawer_printer") or "").strip()
        if drawer_printer:
            if name == drawer_printer:
                chips.append("tortma")
        elif prof.get("drawer") or self.config.get("always_open_drawer"):
            chips.append("tortma")
        if p.get("port"):
            port = p["port"]
            chips.append(port[:22] + "…" if len(port) > 22 else port)
        for c in chips:
            ctk.CTkLabel(info, text=f" {c} ", font=self.F(11),
                         corner_radius=6, fg_color=CHIP,
                         text_color=MUTED).pack(side="left", padx=(0, 6))

        def select(_e=None, n=name):
            self._select_printer(n)
        for w in (card, inner, icon, top, info, *top.winfo_children(),
                  *info.winfo_children(), *icon.winfo_children()):
            w.bind("<Button-1>", select)

        def on_enter(_e=None):
            if name != self._sel_printer:
                card.configure(fg_color=CARD_HOVER)
        def on_leave(_e=None):
            card.configure(fg_color=CARD)
        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        return card

    def _select_printer(self, name: str):
        self._sel_printer = name
        for n, card in self._printer_cards.items():
            card.configure(border_color=ACCENT if n == name else BORDER)

    def _need_selection(self):
        if not self._sel_printer:
            messagebox.showinfo(APP_NAME,
                                "Avval ro'yxatdan printerni tanlang "
                                "(kartochka ustiga bosing).",
                                parent=self.root)
            return None
        return self._sel_printer

    def make_default(self):
        name = self._need_selection()
        if not name:
            return
        self.config.set("default_printer", name)
        self.logger.info("Standart printer: %s", name)
        self.refresh_printers()
        self._toast(f"✓ Standart printer: {name}", GREEN)

    def _center_dialog(self, dlg, w, h):
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
            dlg.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            dlg.geometry(f"{w}x{h}")

    def edit_profile(self):
        name = self._need_selection()
        if not name:
            return
        prof = self.config.profile(name)
        always_drawer = bool(self.config.get("always_open_drawer"))

        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title(f"Profil — {name}")
        self._center_dialog(dlg, 450, 540 if always_drawer else 500)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.after(120, lambda: (_set_titlebar(dlg, self._is_dark()),
                                dlg.grab_set()))

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=22, pady=18)

        head = ctk.CTkFrame(frm, fg_color="transparent")
        head.pack(fill="x", pady=(0, 14))
        hicon = ctk.CTkFrame(head, width=40, height=40, corner_radius=11,
                             fg_color=ACCENT_SOFT)
        hicon.pack(side="left")
        hicon.pack_propagate(False)
        ctk.CTkLabel(hicon, text="🖨", font=self.F(16)).place(
            relx=0.5, rely=0.5, anchor="center")
        hbox = ctk.CTkFrame(head, fg_color="transparent")
        hbox.pack(side="left", padx=10)
        ctk.CTkLabel(hbox, text=name, font=self.F(15, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(hbox, text="Printer profili", font=self.F(11),
                     text_color=MUTED).pack(anchor="w")

        ctk.CTkLabel(frm, text="Rejim", font=self.F(12),
                     text_color=MUTED).pack(anchor="w")
        mode_seg = ctk.CTkSegmentedButton(
            frm, values=["escpos", "windows"], font=self.F(13),
            fg_color=CHIP, unselected_color=CHIP,
            unselected_hover_color=CARD_HOVER,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        mode_seg.set(prof["mode"])
        mode_seg.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(frm, text="escpos — termal (Xprinter va h.k.)   ·   "
                               "windows — oddiy printer",
                     font=self.F(11), text_color=MUTED).pack(anchor="w",
                                                             pady=(0, 10))

        ctk.CTkLabel(frm, text="Qog'oz kengligi", font=self.F(12),
                     text_color=MUTED).pack(anchor="w")
        paper_seg = ctk.CTkSegmentedButton(
            frm, values=["58 mm", "80 mm"], font=self.F(13),
            fg_color=CHIP, unselected_color=CHIP,
            unselected_hover_color=CARD_HOVER,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        paper_seg.set(f'{prof["paper"]} mm')
        paper_seg.pack(fill="x", pady=(4, 10))

        row = ctk.CTkFrame(frm, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(row, text="Maxsus kenglik (nuqta, 0 = avto)",
                     font=self.F(12), text_color=MUTED).pack(side="left")
        dots_entry = ctk.CTkEntry(row, width=90, height=30, corner_radius=8,
                                  fg_color=CARD, border_color=BORDER)
        dots_entry.insert(0, str(prof.get("dots") or 0))
        dots_entry.pack(side="right")

        row2 = ctk.CTkFrame(frm, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(row2, text="Kesishdan oldin bo'sh qatorlar",
                     font=self.F(12), text_color=MUTED).pack(side="left")
        feed_entry = ctk.CTkEntry(row2, width=90, height=30, corner_radius=8,
                                  fg_color=CARD, border_color=BORDER)
        feed_entry.insert(0, str(prof.get("feed_lines", 4)))
        feed_entry.pack(side="right")

        cut_sw = ctk.CTkSwitch(frm, text="Chek oxirida kesish (auto-cutter)",
                               font=self.F(13), progress_color=ACCENT)
        cut_sw.pack(anchor="w", pady=4)
        if prof.get("cut", True):
            cut_sw.select()
        drawer_sw = ctk.CTkSwitch(frm, text="Pul tortmasini ochish",
                                  font=self.F(13), progress_color=ACCENT)
        drawer_sw.pack(anchor="w", pady=4)
        if prof.get("drawer"):
            drawer_sw.select()
        if always_drawer:
            ctk.CTkLabel(frm, text="Sozlamalar → Kassa da «Har doim pul tortmasini "
                                   "ochish» yoqilgan — tortma har bir chekdan keyin "
                                   "baribir ochiladi.",
                         font=self.F(11), text_color=MUTED,
                         wraplength=390, justify="left").pack(anchor="w")

        def save():
            try:
                dots = int(dots_entry.get() or 0)
                feed = int(feed_entry.get() or 4)
            except ValueError:
                messagebox.showerror(APP_NAME, "Raqam kiriting.", parent=dlg)
                return
            self.config.set_profile(name, {
                "mode": mode_seg.get(),
                "paper": int(paper_seg.get().split()[0]),
                "dots": dots, "cut": bool(cut_sw.get()),
                "drawer": bool(drawer_sw.get()), "feed_lines": feed,
            })
            self.logger.info("Profil saqlandi: %s", name)
            dlg.destroy()
            self.refresh_printers()
            self._toast("✓ Profil saqlandi", GREEN)

        btns = ctk.CTkFrame(frm, fg_color="transparent")
        btns.pack(side="bottom", fill="x", pady=(16, 0))
        ctk.CTkButton(btns, text="Saqlash", height=36, corner_radius=9,
                      font=self.F(13, "bold"), fg_color=ACCENT,
                      text_color="white", hover_color=ACCENT_HOVER,
                      command=save).pack(side="right")
        ctk.CTkButton(btns, text="Bekor qilish", height=36, corner_radius=9,
                      font=self.F(13), fg_color=CARD, hover_color=CARD_HOVER,
                      border_width=1, border_color=BORDER, text_color=MUTED,
                      command=dlg.destroy).pack(side="right", padx=8)

    def print_test(self):
        payload = self.manager.test_payload(self._sel_printer)
        self.jobs.submit(payload, "UI sinov")
        self._toast("🖨 Sinov cheki yuborildi")
        self.show_view("jobs")

    def show_preview(self):
        payload = self.manager.test_payload(self._sel_printer)
        try:
            if self._sel_printer:
                img, _ = self.manager.render_job(payload, self._sel_printer)
            else:
                img = self.manager.renderer.render(
                    payload["elements"], paper_dots(PROFILE_DEFAULTS),
                    self.logger)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Render xatosi: {e}",
                                 parent=self.root)
            return

        win = ctk.CTkToplevel(self.root, fg_color=BG)
        win.title("Chek ko'rinishi (sinov)")
        self._center_dialog(win, min(img.width + 70, 660), 650)
        win.after(120, lambda: _set_titlebar(win, self._is_dark()))
        canvas = tk.Canvas(win, bg=col(BG), highlightthickness=0)
        vbar = ctk.CTkScrollbar(win, command=canvas.yview,
                                button_color=BORDER,
                                button_hover_color=MUTED)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y", padx=(0, 4), pady=6)
        canvas.pack(fill="both", expand=True, padx=(10, 0), pady=6)
        photo = ImageTk.PhotoImage(img.convert("RGB"))
        canvas.create_image(20, 12, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, img.width + 40, img.height + 24))
        canvas.photo = photo
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-e.delta // 100, "units"))

    # ================= Vazifalar =================

    def _build_jobs_view(self):
        v = self._views["jobs"]

        toolbar = ctk.CTkFrame(v, fg_color="transparent")
        toolbar.pack(fill="x")
        self._title_block(toolbar, "Vazifalar",
                          "Chop etish navbati va tarix").pack(side="left")
        ctk.CTkButton(toolbar, text="Tarixni tozalash", height=32,
                      corner_radius=9, font=self.F(12), fg_color=CARD,
                      hover_color=CARD_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER,
                      command=self._clear_history).pack(side="right")

        tiles = ctk.CTkFrame(v, fg_color="transparent")
        tiles.pack(fill="x", pady=(12, 4))
        self._stat_labels = {}
        for i, (key, title, color, icon) in enumerate([
                ("total", "Jami", TEXT, "∑"),
                ("done", "Tayyor", GREEN, "✓"),
                ("failed", "Xato", RED, "✕"),
                ("queued", "Navbatda", AMBER, "⏳")]):
            tile = ctk.CTkFrame(tiles, corner_radius=12, fg_color=CARD,
                                border_width=1, border_color=BORDER)
            tile.pack(side="left", expand=True, fill="x",
                      padx=(0 if i == 0 else 8, 0))
            rowf = ctk.CTkFrame(tile, fg_color="transparent")
            rowf.pack(padx=14, pady=10, fill="x")
            ic = ctk.CTkFrame(rowf, width=34, height=34, corner_radius=9,
                              fg_color=CHIP)
            ic.pack(side="left")
            ic.pack_propagate(False)
            ctk.CTkLabel(ic, text=icon, font=self.F(14, "bold"),
                         text_color=color).place(relx=0.5, rely=0.5,
                                                 anchor="center")
            tb = ctk.CTkFrame(rowf, fg_color="transparent")
            tb.pack(side="left", padx=10)
            num = ctk.CTkLabel(tb, text="0", font=self.F(20, "bold"),
                               text_color=color)
            num.pack(anchor="w")
            ctk.CTkLabel(tb, text=title, font=self.F(11),
                         text_color=MUTED).pack(anchor="w")
            self._stat_labels[key] = num

        self.jobs_area = ctk.CTkScrollableFrame(
            v, fg_color="transparent", scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED)
        self.jobs_area.pack(fill="both", expand=True, pady=(10, 0))

    def _clear_history(self):
        self.jobs.clear_history()
        self._refresh_jobs(force=True)
        self._toast("Tarix tozalandi")

    def _refresh_jobs(self, force=False):
        snap = self.jobs.snapshot(60)
        sig = tuple((j["id"], j["status"]) for j in snap)
        stats = self.jobs.stats()
        for key, label in self._stat_labels.items():
            new = stats.get(key, 0)
            old = self._stat_prev.get(key, 0)
            if new != old:
                self._animate_number(label, old, new)
                self._stat_prev[key] = new
        self._set_busy(any(j["status"] in ("navbatda", "chiqarilmoqda")
                           for j in snap))
        if not force and sig == self._jobs_sig:
            return
        self._jobs_sig = sig

        for row in self._job_rows:
            row.destroy()
        self._job_rows = []

        if not snap:
            self._known_job_ids = set()
            box = ctk.CTkFrame(self.jobs_area, fg_color="transparent")
            box.pack(pady=40)
            ctk.CTkLabel(box, text="🧾", font=self.F(40)).pack()
            ctk.CTkLabel(box, text="Hozircha vazifalar yo'q",
                         font=self.F(14, "bold"),
                         text_color=TEXT).pack(pady=(6, 2))
            ctk.CTkLabel(box, text="Chek yuborilganda shu yerda ko'rinadi",
                         font=self.F(12), text_color=MUTED).pack()
            self._job_rows.append(box)
            return

        new_ids = {j["id"] for j in snap} - self._known_job_ids
        for j in snap:
            row = ctk.CTkFrame(self.jobs_area, corner_radius=10,
                               fg_color=CARD, border_width=1,
                               border_color=BORDER)
            row.pack(fill="x", pady=3, padx=2)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=7)
            ctk.CTkLabel(inner, text=f'#{j["id"]}', width=46, anchor="w",
                         font=self.F(12, "bold"),
                         text_color=MUTED).pack(side="left")
            ctk.CTkLabel(inner, text=j["time"], width=70, anchor="w",
                         font=self.F(12),
                         text_color=MUTED).pack(side="left")
            ctk.CTkLabel(inner, text=j["printer"] or "—", anchor="w",
                         font=self.F(13), text_color=TEXT).pack(
                side="left", padx=(6, 0))
            color = STATUS_COLORS.get(j["status"], MUTED)
            badge = ctk.CTkLabel(inner, text=f'●  {j["status"]}',
                                 font=self.F(11, "bold"),
                                 corner_radius=6, fg_color=CHIP,
                                 text_color=color)
            badge.pack(side="right", ipadx=6)
            if j["error"]:
                err = j["error"]
                if len(err) > 58:
                    err = err[:58] + "…"
                ctk.CTkLabel(inner, text=err, font=self.F(11),
                             text_color=RED).pack(side="right", padx=10)
            if j["id"] in new_ids:
                self._flash_row(row)
            self._job_rows.append(row)
        self._known_job_ids = {j["id"] for j in snap}

    # ================= Sozlamalar =================

    def _build_settings_view(self):
        v = self._views["settings"]
        self._title_block(v, "Sozlamalar",
                          "Server va dastur sozlamalari").pack(anchor="w")

        # Bo'limlar aylantiriladigan (scroll) maydonda — kichik ekranda ham
        # barcha sozlamalar va «Saqlash» tugmasi ko'rinadi; sichqoncha
        # g'ildiragi ham ishlaydi (printerlar/vazifalar sahifalaridagi kabi).
        self.settings_area = ctk.CTkScrollableFrame(
            v, fg_color="transparent", scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED)
        self.settings_area.pack(fill="both", expand=True)
        area = self.settings_area

        def section(title, icon):
            card = ctk.CTkFrame(area, corner_radius=14, fg_color=CARD,
                                border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=(12, 0), padx=(0, 4))
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=20, pady=(14, 4))
            ctk.CTkLabel(head, text=f"{icon}  {title}",
                         font=self.F(13, "bold"),
                         text_color=TEXT).pack(side="left")
            return card

        def row(card, label, hint=""):
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=20, pady=7)
            box = ctk.CTkFrame(r, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(box, text=label, font=self.F(13),
                         text_color=TEXT).pack(anchor="w")
            if hint:
                lbl = ctk.CTkLabel(box, text=hint, font=self.F(11),
                                   text_color=MUTED, justify="left",
                                   wraplength=380)
                lbl.pack(anchor="w")

                # Izoh mavjud kenglikka qarab qatorlarga bo'linadi — tor oynada
                # o'ngdagi tugma/ro'yxat siqilib ko'rinmay qolmasin
                def _wrap(e, l=lbl):
                    try:
                        s = float(ctk.ScalingTracker.get_widget_scaling(l)) or 1.0
                    except Exception:
                        s = 1.0
                    w = max(160, int(e.width / s) - 12)
                    try:
                        if abs(int(l.cget("wraplength")) - w) > 4:
                            l.configure(wraplength=w)
                    except Exception:
                        pass
                box.bind("<Configure>", _wrap)
            return r

        # --- server bo'limi ---
        srv = section("Server", "🌐")
        r = row(srv, "Server manzili",
                "127.0.0.1 — faqat shu kompyuter · 0.0.0.0 — tarmoq ham")
        self.host_menu = ctk.CTkOptionMenu(
            r, values=["127.0.0.1", "0.0.0.0"], width=170, height=32,
            corner_radius=8, font=self.F(13), fg_color=CHIP,
            text_color=TEXT, button_color=BORDER, button_hover_color=MUTED)
        self.host_menu.set(self.config.get("host"))
        self.host_menu.pack(side="right")

        r = row(srv, "Port", "standart: 9100")
        self.port_entry = ctk.CTkEntry(r, width=170, height=32,
                                       corner_radius=8, fg_color=CHIP,
                                       border_color=BORDER)
        self.port_entry.insert(0, str(self.config.get("port")))
        self.port_entry.pack(side="right")

        r = row(srv, "API kalit (ixtiyoriy)",
                "kiritilsa, so'rovlarda X-API-Key talab qilinadi")
        self.key_entry = ctk.CTkEntry(r, width=170, height=32,
                                      corner_radius=8, fg_color=CHIP,
                                      border_color=BORDER)
        self.key_entry.insert(0, self.config.get("api_key") or "")
        self.key_entry.pack(side="right")
        ctk.CTkFrame(srv, height=8, fg_color="transparent").pack()

        # --- kassa bo'limi ---
        kas = section("Kassa", "💵")
        r = row(kas, "Har doim pul tortmasini ochish",
                "yoqilsa har bir chekdan keyin tortma ochiladi — printer, rejim "
                "(escpos / windows / PDF) va so'rovdagi «drawer» qiymatidan "
                "qat'i nazar")
        self.drawer_sw = ctk.CTkSwitch(r, text="", width=44,
                                       progress_color=ACCENT)
        self.drawer_sw.pack(side="right")
        if self.config.get("always_open_drawer"):
            self.drawer_sw.select()

        r = row(kas, "Tortma ulangan printer",
                "impuls doim shu printerga yuboriladi; «(chek printeri)» — chek "
                "qaysi printerga chiqsa, o'shanga")
        self.drawer_printer_menu = ctk.CTkOptionMenu(
            r, values=self._drawer_printer_values(), width=200, height=32,
            corner_radius=8, font=self.F(13), fg_color=CHIP,
            text_color=TEXT, button_color=BORDER, button_hover_color=MUTED)
        self.drawer_printer_menu.set(
            (self.config.get("drawer_printer") or "").strip() or DRAWER_ANY)
        self.drawer_printer_menu.pack(side="right")
        ctk.CTkFrame(kas, height=8, fg_color="transparent").pack()

        # --- dastur bo'limi ---
        appc = section("Dastur", "⚙")
        pad = {"padx": 20, "pady": 6}
        self.min_sw = ctk.CTkSwitch(appc, text="Yashirin holda ishga "
                                               "tushirish (trayda)",
                                    font=self.F(13), progress_color=ACCENT)
        self.min_sw.pack(anchor="w", **pad)
        if self.config.get("start_minimized"):
            self.min_sw.select()

        self.tray_sw = ctk.CTkSwitch(appc, text="Yopilganda trayga yashirish "
                                                "(fonda ishlash)",
                                     font=self.F(13), progress_color=ACCENT)
        self.tray_sw.pack(anchor="w", **pad)
        if self.config.get("close_to_tray", True):
            self.tray_sw.select()

        self.auto_sw = ctk.CTkSwitch(appc, text="Windows bilan birga ishga "
                                                "tushirish",
                                     font=self.F(13), progress_color=ACCENT)
        self.auto_sw.pack(anchor="w", **pad)
        try:
            if get_autostart():
                self.auto_sw.select()
        except Exception:
            pass

        foot = ctk.CTkFrame(appc, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=(8, 16))
        self.save_btn = ctk.CTkButton(foot, text="Saqlash", width=130,
                                      height=36, corner_radius=9,
                                      font=self.F(13, "bold"),
                                      fg_color=ACCENT, text_color="white",
                                      hover_color=ACCENT_HOVER,
                                      command=self.save_settings)
        self.save_btn.pack(side="left")
        self.settings_note = ctk.CTkLabel(foot, text="", font=self.F(12))
        self.settings_note.pack(side="left", padx=14)

    def save_settings(self):
        try:
            port = int(self.port_entry.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME,
                                 "Port 1..65535 oralig'ida bo'lishi kerak.",
                                 parent=self.root)
            return
        old_port = self.config.get("port")
        old_host = self.config.get("host")
        new_host = self.host_menu.get().strip() or "127.0.0.1"
        self.config.set("host", new_host, save=False)
        self.config.set("port", port, save=False)
        self.config.set("api_key", self.key_entry.get().strip(), save=False)
        self.config.set("start_minimized", bool(self.min_sw.get()), save=False)
        self.config.set("close_to_tray", bool(self.tray_sw.get()), save=False)
        self.config.set("always_open_drawer", bool(self.drawer_sw.get()),
                        save=False)
        choice = (self.drawer_printer_menu.get() or "").strip()
        self.config.set("drawer_printer",
                        "" if choice == DRAWER_ANY else choice, save=False)
        self.config.save()
        try:
            set_autostart(bool(self.auto_sw.get()))
        except Exception as e:
            self.logger.warning("Autostart sozlanmadi: %s", e)

        # tugmaning muvaffaqiyat animatsiyasi
        try:
            self.save_btn.configure(text="✓ Saqlandi", fg_color=GREEN,
                                    hover_color=GREEN)
            self.root.after(1600, lambda: self.save_btn.configure(
                text="Saqlash", fg_color=ACCENT, hover_color=ACCENT_HOVER)
                if not self._quitting else None)
        except Exception:
            pass
        if port != old_port or new_host != old_host:
            self._flash_note(self.settings_note,
                             "Yangi port/manzil dastur qayta ochilganda "
                             "kuchga kiradi", AMBER)
        self.logger.info("Sozlamalar saqlandi")
        # printer kartochkalaridagi «tortma» belgisi yangilansin
        self.refresh_printers()

    # ================= Jurnal =================

    def _build_logs_view(self):
        v = self._views["logs"]
        self._title_block(v, "Jurnal",
                          "Dastur hodisalari va xatolar").pack(anchor="w")
        self.log_text = ctk.CTkTextbox(
            v, corner_radius=14, fg_color=CARD, border_width=1,
            border_color=BORDER, text_color=MUTED, font=self.MONO,
            wrap="none", state="disabled",
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=MUTED)
        self.log_text.pack(fill="both", expand=True, pady=(12, 0))

    def _refresh_logs(self):
        lines = tail_logs(300)
        sig = (len(lines), lines[-1] if lines else "")
        if sig == self._log_sig:
            return
        self._log_sig = sig
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        # darajalarga qarab ranglash
        try:
            tb = self.log_text._textbox
            tb.tag_config("warn", foreground=col(AMBER))
            tb.tag_config("err", foreground=col(RED))
            tagged = True
        except Exception:
            tagged = False
        for ln in lines:
            tag = ()
            if tagged:
                if " WARNING" in ln:
                    tag = ("warn",)
                elif " ERROR" in ln or " CRITICAL" in ln:
                    tag = ("err",)
            self.log_text.insert("end", ln + "\n", *((tag,) if tag else ()))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ================= hodisalar =================

    def _poll_tray(self):
        try:
            while True:
                action = self.tray.actions.get_nowait()
                if action == "show":
                    self.show()
                elif action == "test":
                    self.jobs.submit(self.manager.test_payload(None),
                                     "tray sinov")
                elif action == "quit":
                    self.quit()
        except Exception:
            pass
        if not self._quitting:
            self.root.after(300, self._poll_tray)

    def _poll_data(self):
        try:
            self._refresh_jobs()
            self._refresh_logs()
            self._update_status_label()
        except Exception:
            pass
        if not self._quitting:
            self.root.after(700, self._poll_data)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._fade_in()

    def hide(self):
        self.root.withdraw()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.notify("TPrints fonda ishlashda davom etmoqda. "
                             "Ochish uchun tray belgisini bosing.")

    def confirm_quit(self):
        """Tasdiq bilan dasturni butunlay yopish."""
        if messagebox.askyesno(
                APP_NAME,
                "Dasturni butunlay yopmoqchimisiz?\n\n"
                "Fon xizmati ham to'xtaydi — dastur qayta ochilguncha "
                "cheklar qabul qilinmaydi.\n"
                "Barcha sozlamalar saqlanadi.",
                parent=self.root):
            self.quit()

    def on_close(self):
        if self.config.get("close_to_tray", True):
            self.hide()
        else:
            self.quit()

    def quit(self):
        self._quitting = True
        self.logger.info("Dastur yopilmoqda")
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self, start_minimized=False):
        if start_minimized:
            self.root.withdraw()
        else:
            self._fade_in()
        self.root.mainloop()
