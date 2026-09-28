"""Print manager: vazifani render qilib, mos rejimda printerga yuboradi."""
import base64
import time

from PIL import Image

from ..config import Config, paper_dots
from . import escpos, win_printer
from .renderer import ReceiptRenderer


class PrintError(Exception):
    pass


class PrintManager:
    def __init__(self, config: Config, logger):
        self.config = config
        self.logger = logger
        self.renderer = ReceiptRenderer()

    # ---------- yordamchilar ----------

    def resolve_printer(self, requested: str) -> str:
        name = (requested or "").strip()
        if not name:
            name = self.config.get("default_printer") or ""
        if not name:
            name = win_printer.default_printer()
        if not name:
            raise PrintError("Printer topilmadi: standart printer o'rnatilmagan")
        return name

    def profile_for(self, printer_name: str, overrides: dict = None) -> dict:
        prof = self.config.profile(printer_name)
        if overrides:
            for k in ("mode", "paper", "dots", "cut", "feed_lines", "drawer"):
                if k in overrides and overrides[k] is not None:
                    prof[k] = overrides[k]
        return prof

    def render_job(self, payload: dict, printer_name: str = None):
        """Vazifadan (JSON) chek rasmini yasash. (rasm, profil) qaytaradi."""
        printer_name = printer_name or self.resolve_printer(payload.get("printer"))
        prof = self.profile_for(printer_name, payload)
        dots = paper_dots(prof)

        if payload.get("elements") is not None:
            img = self.renderer.render(payload["elements"], dots, self.logger)
        elif payload.get("text") is not None:
            img = self.renderer.render_text_plain(str(payload["text"]), dots)
        elif payload.get("image_base64"):
            img = self.renderer.render(
                [{"type": "image", "base64": payload["image_base64"],
                  "width_pct": payload.get("width_pct", 100)}], dots, self.logger)
        else:
            raise PrintError("Bo'sh vazifa: 'elements', 'text' yoki 'image_base64' kerak")
        return img, prof

    # ---------- PDF / A4 hujjatlar ----------

    @staticmethod
    def render_pdf_pages(pdf_bytes: bytes, dpi: int = 200) -> list:
        """PDF sahifalarini rasmga aylantiradi (PyMuPDF)."""
        try:
            try:
                import pymupdf as mupdf
            except ImportError:  # eski nom
                import fitz as mupdf
        except ImportError as e:
            raise PrintError("PDF chop etish uchun PyMuPDF kerak: pip install pymupdf") from e
        pages = []
        with mupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=max(72, min(int(dpi), 300)), alpha=False)
                pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        if not pages:
            raise PrintError("PDF bo'sh")
        return pages

    def print_document(self, payload: dict) -> dict:
        """PDF hujjat (natija, A4): sahifalar rasmga aylantirilib Windows drayveri orqali chiqariladi.
        Faqat 'windows' rejimidagi (oddiy/lazer) printerga — termal chek printeriga A4 chiqmaydi."""
        printer_name = self.resolve_printer(payload.get("printer"))
        prof = self.profile_for(printer_name)
        if prof.get("mode") != "windows":
            raise PrintError(f"'{printer_name}' — termal (ESC/POS) printer. A4 hujjatni oddiy printerga chiqaring "
                             "(Sozlamalar → Profil → rejim 'windows')")
        copies = max(1, min(int(payload.get("copies") or 1), 20))
        pdf_bytes = base64.b64decode(payload["pdf_base64"])
        pages = self.render_pdf_pages(pdf_bytes, int(payload.get("dpi") or 200))
        doc_name = str(payload.get("doc_name") or "TPrints hujjat")[:120]
        for _ in range(copies):
            self._send_with_retry(
                lambda: win_printer.print_pages_gdi(printer_name, pages, doc_name))
        result = {"printer": printer_name, "mode": "pdf", "copies": copies,
                  "pages": len(pages), "width_px": pages[0].width, "height_px": pages[0].height}
        wanted, target = self._drawer_plan(printer_name, prof)
        if wanted:
            result.update(self._kick_drawer(target))
        return result

    # ---------- pul tortmasi ----------

    def _drawer_plan(self, printer_name: str, prof: dict = None):
        """Tortma ochish kerakmi va impuls qaysi printerga ketadi: (kerak, printer).

        Kerak: global "always_open_drawer" yoqiq bo'lsa — har doim; aks holda
        profil/so'rovdagi "drawer" bo'yicha. Printer: sozlamalardagi
        "drawer_printer" (tortma ulangan printer), bo'sh bo'lsa chek chiqqan printer.
        """
        wanted = (bool(self.config.get("always_open_drawer")) or
                  bool((prof or {}).get("drawer", False)))
        target = (self.config.get("drawer_printer") or "").strip() or printer_name
        return wanted, target

    def _kick_drawer(self, printer_name: str) -> dict:
        """Tortma impulsini alohida RAW vazifa sifatida yuboradi (chek chiqqandan keyin).

        Har qanday rejimdagi (escpos / windows / PDF) chekdan keyin ishlaydi: RAW
        baytlar Windows spooler orqali drayverni chetlab to'g'ridan-to'g'ri portga
        boradi. Xato bo'lsa chek "xato" deb belgilanmaydi (chek allaqachon chiqqan) —
        faqat log va natijaga yoziladi.
        """
        try:
            self._send_with_retry(lambda: win_printer.send_raw(
                printer_name, escpos.DRAWER_KICK, doc_name="TPrints tortma"))
            return {"drawer": True, "drawer_printer": printer_name}
        except Exception as e:
            self.logger.warning("Tortma ochilmadi (%s): %s", printer_name, e)
            return {"drawer": False, "drawer_printer": printer_name,
                    "drawer_error": str(e)}

    # ---------- chop etish ----------

    def print_job(self, payload: dict) -> dict:
        """To'liq vazifa: render + yuborish. Xatoda PrintError ko'taradi."""
        if payload.get("pdf_base64"):
            return self.print_document(payload)
        printer_name = self.resolve_printer(payload.get("printer"))
        copies = max(1, min(int(payload.get("copies") or 1), 20))

        if payload.get("raw_base64"):
            # Tayyor ESC/POS baytlar (ilg'or foydalanish). Tortma faqat global
            # sozlama bo'yicha: o'sha printerga — baytlar oxiriga qo'shiladi,
            # boshqa printerga — alohida impuls.
            wanted, target = self._drawer_plan(printer_name)
            data = base64.b64decode(payload["raw_base64"])
            inline = wanted and target == printer_name
            if inline:
                data += escpos.DRAWER_KICK
            for _ in range(copies):
                self._send_with_retry(
                    lambda: win_printer.send_raw(printer_name, data))
            sent = {"printer": printer_name, "mode": "raw", "copies": copies,
                    "bytes": len(data), "drawer": inline}
            if wanted and not inline:
                sent.update(self._kick_drawer(target))
            return sent

        img, prof = self.render_job(payload, printer_name)
        wanted, target = self._drawer_plan(printer_name, prof)

        if prof["mode"] == "escpos":
            # Tortma o'sha printerda bo'lsa impuls chek baytlari oxiriga (kesishdan
            # keyin) qo'shiladi; boshqa printerda bo'lsa alohida yuboriladi.
            inline = wanted and target == printer_name
            data = escpos.build_receipt(
                img,
                cut=bool(prof.get("cut", True)),
                feed_lines=int(prof.get("feed_lines", 4)),
                drawer=inline,
                chunk_height=int(self.config.get("raster_chunk") or 256),
            )
            for _ in range(copies):
                self._send_with_retry(
                    lambda: win_printer.send_raw(printer_name, data))
            sent = {"mode": "escpos", "bytes": len(data), "drawer": inline}
        else:
            # Windows drayveri (GDI) — ESC/POS baytlar yo'q, shuning uchun tortma
            # impulsi chekdan keyin alohida RAW vazifa bilan yuboriladi.
            inline = False
            for _ in range(copies):
                self._send_with_retry(
                    lambda: win_printer.print_image_gdi(printer_name, img))
            sent = {"mode": "windows", "drawer": False}

        sent.update({"printer": printer_name, "copies": copies,
                     "height_px": img.height, "width_px": img.width})
        if wanted and not inline:
            sent.update(self._kick_drawer(target))
        return sent

    def _send_with_retry(self, fn):
        retries = max(0, int(self.config.get("retries") or 0))
        delay = float(self.config.get("retry_delay") or 1.5)
        last = None
        for attempt in range(retries + 1):
            try:
                fn()
                return
            except Exception as e:
                last = e
                self.logger.warning("Yuborish xatosi (urinish %d/%d): %s",
                                    attempt + 1, retries + 1, e)
                if attempt < retries:
                    time.sleep(delay)
        raise PrintError(f"Printerga yuborib bo'lmadi: {last}")

    # ---------- test chek ----------

    def test_payload(self, printer_name: str = None) -> dict:
        from datetime import datetime
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        return {
            "printer": printer_name,
            "elements": [
                {"type": "title", "value": "TPrints", "size": 3},
                {"type": "text", "value": "Sinov cheki / Тестовый чек",
                 "align": "center"},
                {"type": "line", "char": "="},
                {"type": "row", "left": "Printer:",
                 "right": (printer_name or "standart")[:24]},
                {"type": "row", "left": "Vaqt:", "right": now},
                {"type": "line"},
                {"type": "table",
                 "headers": ["Mahsulot", "Soni", "Narx"],
                 "widths": [3, 1, 2],
                 "rows": [["Osh", "1", "35 000"],
                          ["Choy (ko'k)", "2", "6 000"],
                          ["Non", "1", "4 000"]]},
                {"type": "line", "char": "-"},
                {"type": "row", "left": "JAMI:", "right": "45 000 so'm",
                 "bold": True, "size": 2},
                {"type": "qr", "value": "https://example.uz/chek/12345", "size": 5},
                {"type": "text", "value": "Xaridingiz uchun rahmat!",
                 "align": "center", "bold": True},
            ],
        }
