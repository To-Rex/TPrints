"""Chek dizaynini (JSON) rasmga chizuvchi dvigatel.

Chek elementlar ro'yxati sifatida keladi va 203dpi monoxrom rasmga chiziladi.
Rasm sifatida chop etilgani uchun istalgan dizayn, istalgan til (lotin, kirill,
Unicode), QR, shtrix-kod, logo va uzun cheklar cheklovsiz qo'llab-quvvatlanadi.

Element turlari:
  text     - {value, align, bold, size(1-4)|font_size, mono, underline, gap}
  title    - text bilan bir xil, lekin standart: bold, size=2, center
  line     - {char, thickness, style: solid|dashed}  ajratuvchi chiziq
  row      - {left, right, bold, size, mono}  chap-o'ng (nom — narx) qatori
  columns  - {cols: [{text, width, align, bold, size}]}  ustunlar
  table    - {headers, rows, widths, aligns, bold_header, size}
  image    - {base64|path, width_pct, align, dither}
  qr       - {value, size(1-12), align}
  barcode  - {value, kind: code128|ean13|ean8, height, text, align}
  feed     - {lines}  bo'sh qatorlar
  space    - {px}     piksellarda bo'sh joy
"""
import base64
import io
import os
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

# (oddiy, qalin) juftliklari — birinchisi topilgani ishlatiladi
FONT_CANDIDATES = [("arial.ttf", "arialbd.ttf"),
                   ("segoeui.ttf", "segoeuib.ttf"),
                   ("tahoma.ttf", "tahomabd.ttf")]
MONO_CANDIDATES = [("consola.ttf", "consolab.ttf"),
                   ("cour.ttf", "courbd.ttf")]

BASE_SIZE = 24            # size=1 uchun shrift balandligi (px, 203dpi ~ 3mm)
SIZE_STEPS = {1: 24, 2: 32, 3: 42, 4: 56}
SIDE_PAD = 6              # chap/o'ng ichki maydon (px)
DEFAULT_GAP = 6           # elementlar orasidagi masofa (px)

WHITE = 255
BLACK = 0


def _find_font_pair(candidates):
    for normal, bold in candidates:
        p1 = os.path.join(FONT_DIR, normal)
        p2 = os.path.join(FONT_DIR, bold)
        if os.path.exists(p1):
            return p1, (p2 if os.path.exists(p2) else p1)
    return None, None


class ReceiptRenderer:
    def __init__(self):
        self._normal, self._normal_bold = _find_font_pair(FONT_CANDIDATES)
        self._mono, self._mono_bold = _find_font_pair(MONO_CANDIDATES)
        self._cache = {}

    # ---------- shriftlar ----------

    def font(self, size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
        key = (size, bold, mono)
        if key in self._cache:
            return self._cache[key]
        if mono:
            path = self._mono_bold if bold else self._mono
        else:
            path = self._normal_bold if bold else self._normal
        if path:
            f = ImageFont.truetype(path, size)
        else:
            f = ImageFont.load_default(size)
        self._cache[key] = f
        return f

    def _el_font(self, el: dict) -> ImageFont.FreeTypeFont:
        fs = el.get("font_size")
        if not fs:
            fs = SIZE_STEPS.get(int(el.get("size") or 1), BASE_SIZE)
        return self.font(int(fs), bool(el.get("bold")), bool(el.get("mono")))

    # ---------- yordamchilar ----------

    @staticmethod
    def _text_w(font, text) -> int:
        return int(font.getlength(text))

    @staticmethod
    def _line_h(font) -> int:
        ascent, descent = font.getmetrics()
        return ascent + descent

    def _wrap(self, text: str, font, max_w: int):
        """So'z bo'yicha o'rash; juda uzun so'zlar harfma-harf bo'linadi."""
        lines = []
        max_w = max(max_w, 10)
        for raw_line in str(text).split("\n"):
            if not raw_line:
                lines.append("")
                continue
            words = raw_line.split(" ")
            cur = ""
            for word in words:
                trial = (cur + " " + word) if cur else word
                if self._text_w(font, trial) <= max_w:
                    cur = trial
                    continue
                if cur:
                    lines.append(cur)
                    cur = ""
                # so'zning o'zi sig'masa — bo'lak-bo'lak qilamiz
                while self._text_w(font, word) > max_w:
                    lo, hi = 1, len(word)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if self._text_w(font, word[:mid]) <= max_w:
                            lo = mid
                        else:
                            hi = mid - 1
                    lines.append(word[:lo])
                    word = word[lo:]
                cur = word
            lines.append(cur)
        return lines or [""]

    @staticmethod
    def _x_for(align: str, width: int, item_w: int) -> int:
        if align == "center":
            return max(0, (width - item_w) // 2)
        if align == "right":
            return max(0, width - item_w)
        return 0

    @staticmethod
    def _blank(width: int, height: int) -> Image.Image:
        return Image.new("L", (width, max(height, 1)), WHITE)

    # ---------- elementlar ----------

    def _render_text(self, el: dict, width: int) -> Image.Image:
        font = self._el_font(el)
        align = el.get("align", "left")
        value = el.get("value", el.get("text", ""))
        lines = self._wrap(value, font, width)
        lh = self._line_h(font)
        img = self._blank(width, lh * len(lines))
        draw = ImageDraw.Draw(img)
        y = 0
        for ln in lines:
            w = self._text_w(font, ln)
            x = self._x_for(align, width, w)
            draw.text((x, y), ln, font=font, fill=BLACK)
            if el.get("underline") and ln:
                draw.line([(x, y + lh - 2), (x + w, y + lh - 2)], fill=BLACK, width=2)
            y += lh
        return img

    def _render_title(self, el: dict, width: int) -> Image.Image:
        merged = {"align": "center", "bold": True, "size": 2}
        merged.update(el)
        return self._render_text(merged, width)

    def _render_line(self, el: dict, width: int) -> Image.Image:
        char = el.get("char")
        if char:
            font = self.font(SIZE_STEPS.get(int(el.get("size") or 1), BASE_SIZE),
                             mono=True)
            cw = max(1, self._text_w(font, char))
            count = max(1, width // cw)
            return self._render_text({"value": char * count, "mono": True,
                                      "size": el.get("size", 1)}, width)
        thickness = int(el.get("thickness") or 2)
        img = self._blank(width, thickness + 6)
        draw = ImageDraw.Draw(img)
        y = 3 + thickness // 2
        if el.get("style") == "dashed":
            x = 0
            while x < width:
                draw.line([(x, y), (min(x + 12, width), y)], fill=BLACK, width=thickness)
                x += 20
        else:
            draw.line([(0, y), (width, y)], fill=BLACK, width=thickness)
        return img

    def _render_row(self, el: dict, width: int) -> Image.Image:
        font = self._el_font(el)
        left = str(el.get("left", ""))
        right = str(el.get("right", ""))
        gap = 12
        right_w = self._text_w(font, right)
        right_w = min(right_w, int(width * 0.6))
        left_lines = self._wrap(left, font, width - right_w - gap)
        lh = self._line_h(font)
        img = self._blank(width, lh * len(left_lines))
        draw = ImageDraw.Draw(img)
        y = 0
        for ln in left_lines:
            draw.text((0, y), ln, font=font, fill=BLACK)
            y += lh
        draw.text((width - self._text_w(font, right), 0), right, font=font, fill=BLACK)
        return img

    def _render_columns(self, el: dict, width: int) -> Image.Image:
        cols = el.get("cols") or []
        if not cols:
            return self._blank(width, 1)
        weights = [max(float(c.get("width") or 1), 0.05) for c in cols]
        total = sum(weights)
        gap = 8
        avail = width - gap * (len(cols) - 1)
        col_ws = [max(int(avail * w / total), 12) for w in weights]

        rendered, max_h = [], 1
        for c, cw in zip(cols, col_ws):
            sub = {"value": c.get("text", ""), "align": c.get("align", "left"),
                   "bold": c.get("bold", el.get("bold")),
                   "size": c.get("size", el.get("size", 1)),
                   "font_size": c.get("font_size", el.get("font_size")),
                   "mono": c.get("mono", el.get("mono"))}
            im = self._render_text(sub, cw)
            rendered.append(im)
            max_h = max(max_h, im.height)

        img = self._blank(width, max_h)
        x = 0
        for im, cw in zip(rendered, col_ws):
            img.paste(im, (x, 0))
            x += cw + gap
        return img

    def _render_table(self, el: dict, width: int) -> Image.Image:
        headers = el.get("headers") or []
        rows = el.get("rows") or []
        n = max(len(headers), max((len(r) for r in rows), default=0))
        if n == 0:
            return self._blank(width, 1)
        widths = el.get("widths") or [1] * n
        widths = (list(widths) + [1] * n)[:n]
        aligns = el.get("aligns") or (["left"] + ["right"] * (n - 1))
        aligns = (list(aligns) + ["left"] * n)[:n]

        parts = []
        if headers:
            parts.append(self._render_columns({
                "cols": [{"text": h, "width": widths[i], "align": aligns[i],
                          "bold": el.get("bold_header", True),
                          "size": el.get("size", 1)}
                         for i, h in enumerate(list(headers) + [""] * (n - len(headers)))]
            }, width))
            parts.append(self._render_line({"thickness": 2}, width))
        for r in rows:
            r = list(r) + [""] * (n - len(r))
            parts.append(self._render_columns({
                "cols": [{"text": str(cell), "width": widths[i], "align": aligns[i],
                          "size": el.get("size", 1)}
                         for i, cell in enumerate(r)]
            }, width))
        return self._stack(parts, width, gap=3)

    def _load_image(self, el: dict) -> Image.Image:
        b64 = el.get("base64") or el.get("data")
        if b64:
            b64 = re.sub(r"^data:image/[a-zA-Z0-9.+-]+;base64,", "", b64.strip())
            return Image.open(io.BytesIO(base64.b64decode(b64)))
        path = el.get("path")
        if path and os.path.exists(path):
            return Image.open(path)
        raise ValueError("image element: 'base64' yoki mavjud 'path' kerak")

    def _render_image(self, el: dict, width: int) -> Image.Image:
        src = self._load_image(el)
        if src.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
            bg.alpha_composite(src.convert("RGBA"))
            src = bg
        src = src.convert("L")
        pct = max(5, min(int(el.get("width_pct") or 60), 100))
        target_w = min(int(width * pct / 100), width)
        target_h = max(1, int(src.height * target_w / max(src.width, 1)))
        src = src.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if el.get("dither", True):
            src = src.convert("1").convert("L")  # Floyd-Steinberg dizering
        else:
            src = src.point(lambda p: WHITE if p >= 128 else BLACK)
        img = self._blank(width, target_h)
        img.paste(src, (self._x_for(el.get("align", "center"), width, target_w), 0))
        return img

    def _render_qr(self, el: dict, width: int) -> Image.Image:
        import qrcode
        value = str(el.get("value", ""))
        box = max(2, min(int(el.get("size") or 6), 12))
        qr = qrcode.QRCode(border=1, box_size=box,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(value)
        qr.make(fit=True)
        qim = qr.make_image(fill_color="black", back_color="white").convert("L")
        if qim.width > width:
            qim = qim.resize((width, width), Image.Resampling.NEAREST)
        img = self._blank(width, qim.height)
        img.paste(qim, (self._x_for(el.get("align", "center"), width, qim.width), 0))
        return img

    def _render_barcode(self, el: dict, width: int) -> Image.Image:
        value = str(el.get("value", ""))
        kind = (el.get("kind") or "code128").lower()
        height_px = max(30, min(int(el.get("height") or 90), 300))
        try:
            import barcode as pybarcode
            from barcode.writer import ImageWriter
            cls = pybarcode.get_barcode_class(kind)
            writer = ImageWriter()
            opts = {"module_width": 0.25, "module_height": height_px * 25.4 / 203,
                    "quiet_zone": 1.5, "font_size": 0 if not el.get("text", True) else 9,
                    "text_distance": 3, "dpi": 203, "write_text": bool(el.get("text", True))}
            obj = cls(value, writer=writer)
            buf = io.BytesIO()
            obj.write(buf, options=opts)
            buf.seek(0)
            bimg = Image.open(buf).convert("L")
        except Exception as e:
            # Yaroqsiz qiymat (masalan EAN13 uchun raqam emas) — matn sifatida
            return self._render_text({"value": f"[{kind}: {value}]",
                                      "align": "center"}, width)
        if bimg.width > width:
            ratio = width / bimg.width
            bimg = bimg.resize((width, max(1, int(bimg.height * ratio))),
                               Image.Resampling.LANCZOS)
            bimg = bimg.point(lambda p: WHITE if p >= 128 else BLACK)
        img = self._blank(width, bimg.height)
        img.paste(bimg, (self._x_for(el.get("align", "center"), width, bimg.width), 0))
        return img

    def _render_feed(self, el: dict, width: int) -> Image.Image:
        lines = max(0, min(int(el.get("lines") or 1), 50))
        return self._blank(width, lines * self._line_h(self.font(BASE_SIZE)))

    def _render_space(self, el: dict, width: int) -> Image.Image:
        return self._blank(width, max(0, min(int(el.get("px") or 10), 2000)))

    # ---------- yig'ish ----------

    @staticmethod
    def _stack(parts, width: int, gap: int = DEFAULT_GAP) -> Image.Image:
        parts = [p for p in parts if p is not None and p.height > 0]
        if not parts:
            return Image.new("L", (width, 1), WHITE)
        total_h = sum(p.height for p in parts) + gap * (len(parts) - 1)
        img = Image.new("L", (width, total_h), WHITE)
        y = 0
        for p in parts:
            img.paste(p, (0, y))
            y += p.height + gap
        return img

    def render(self, elements: list, dots: int, logger=None) -> Image.Image:
        """Elementlar ro'yxatini to'liq chek rasmiga aylantiradi."""
        content_w = dots - SIDE_PAD * 2
        handlers = {
            "text": self._render_text, "title": self._render_title,
            "line": self._render_line, "divider": self._render_line,
            "row": self._render_row, "kv": self._render_row,
            "columns": self._render_columns, "table": self._render_table,
            "image": self._render_image, "logo": self._render_image,
            "qr": self._render_qr, "barcode": self._render_barcode,
            "feed": self._render_feed, "space": self._render_space,
        }
        parts = []
        for i, el in enumerate(elements or []):
            if not isinstance(el, dict):
                el = {"type": "text", "value": str(el)}
            etype = str(el.get("type", "text")).lower()
            handler = handlers.get(etype)
            if handler is None:
                if logger:
                    logger.warning("Noma'lum element turi o'tkazib yuborildi: %r", etype)
                continue
            try:
                part = handler(el, content_w)
            except Exception as e:
                if logger:
                    logger.warning("Element #%d (%s) xatosi: %s", i, etype, e)
                part = self._render_text(
                    {"value": f"[element xatosi: {etype}]", "align": "center"}, content_w)
            gap = el.get("gap")
            if gap is not None:
                pad = self._blank(content_w, max(0, min(int(gap), 500)))
                part = self._stack([part, pad], content_w, gap=0)
            parts.append(part)

        body = self._stack(parts, content_w)
        img = Image.new("L", (dots, body.height + 8), WHITE)
        img.paste(body, (SIDE_PAD, 4))
        return img

    def render_text_plain(self, text: str, dots: int) -> Image.Image:
        """Oddiy matnni (mono shriftda) chekka aylantirish."""
        return self.render([{"type": "text", "value": text, "mono": True}], dots)
