"""Windows printer bilan ishlash: ro'yxat, RAW yuborish, GDI orqali chop etish."""
import win32print
import win32ui
from PIL import Image, ImageWin

# GetDeviceCaps konstantalari
HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90

PRINTER_STATUS_LABELS = {
    0x00000001: "pauza", 0x00000002: "xato", 0x00000010: "qog'oz tugagan",
    0x00000080: "oflayn", 0x00000200: "band", 0x00000400: "chop etmoqda",
    0x00400000: "eshik ochiq", 0x00080000: "qog'oz kam",
}
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400


def list_printers() -> list:
    """Barcha lokal va ulangan printerlar."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = []
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""
    for p in win32print.EnumPrinters(flags, None, 2):
        name = p.get("pPrinterName", "")
        status_bits = p.get("Status", 0) or 0
        attrs = p.get("Attributes", 0) or 0
        problems = [label for bit, label in PRINTER_STATUS_LABELS.items()
                    if status_bits & bit]
        if attrs & PRINTER_ATTRIBUTE_WORK_OFFLINE:
            problems.append("oflayn (Windows)")
        printers.append({
            "name": name,
            "port": p.get("pPortName", ""),
            "driver": p.get("pDriverName", ""),
            "default": name == default,
            "status": ", ".join(problems) if problems else "tayyor",
        })
    return printers


def default_printer() -> str:
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


def send_raw(printer_name: str, data: bytes, doc_name: str = "TPrints chek"):
    """RAW baytlarni (ESC/POS) to'g'ridan-to'g'ri printerga yuborish."""
    h = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(h, 1, (doc_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, bytes(data))
            win32print.EndPagePrinter(h)
            if written != len(data):
                raise OSError(f"To'liq yozilmadi: {written}/{len(data)} bayt")
        finally:
            win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def print_pages_gdi(printer_name: str, pages, doc_name: str = "TPrints hujjat"):
    """Har bir rasm — alohida sahifa (A4 hujjatlar, PDF). Rasm sahifaga sig'diriladi va markazlanadi."""
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    try:
        page_w = hdc.GetDeviceCaps(HORZRES)
        page_h = hdc.GetDeviceCaps(VERTRES)
        hdc.StartDoc(doc_name)
        try:
            for img in pages:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                scale = min(page_w / float(img.width), page_h / float(img.height))
                w = max(1, int(img.width * scale))
                h = max(1, int(img.height * scale))
                x = (page_w - w) // 2
                y = (page_h - h) // 2
                hdc.StartPage()
                ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (x, y, x + w, y + h))
                hdc.EndPage()
        finally:
            hdc.EndDoc()
    finally:
        hdc.DeleteDC()


def print_image_gdi(printer_name: str, img: Image.Image, src_dpi: int = 203,
                    doc_name: str = "TPrints chek"):
    """Rasmni Windows drayveri (GDI) orqali chop etish.

    Oddiy printerlar (lazer, siyohli, A4) uchun. Chek haqiqiy o'lchamda
    (58/80mm kenglikda) chiqadi; uzun cheklar sahifalarga bo'linadi.
    """
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    try:
        page_w = hdc.GetDeviceCaps(HORZRES)
        page_h = hdc.GetDeviceCaps(VERTRES)
        dpi_x = hdc.GetDeviceCaps(LOGPIXELSX) or 300

        scale = dpi_x / float(src_dpi)
        target_w = min(int(img.width * scale), page_w)
        scale = target_w / float(img.width)
        page_h_src = max(1, int(page_h / scale))

        if img.mode != "RGB":
            img = img.convert("RGB")

        hdc.StartDoc(doc_name)
        try:
            for top in range(0, img.height, page_h_src):
                band = img.crop((0, top, img.width, min(top + page_h_src, img.height)))
                hdc.StartPage()
                dib = ImageWin.Dib(band)
                out_h = max(1, int(band.height * scale))
                dib.draw(hdc.GetHandleOutput(), (0, 0, target_w, out_h))
                hdc.EndPage()
        finally:
            hdc.EndDoc()
    finally:
        hdc.DeleteDC()
