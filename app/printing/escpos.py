"""ESC/POS buyruqlari: rasmni raster formatga o'girish, kesish, pul tortmasi.

Xprinter va deyarli barcha termal chek printerlari GS v 0 raster formatini
qo'llab-quvvatlaydi. Chek to'liq rasm sifatida yuboriladi — shuning uchun
har qanday til (lotin/kirill), shrift va dizayn muammosiz chiqadi.
"""
from PIL import Image

INIT = b"\x1b\x40"                    # ESC @  - printerni tozalash
CUT_PARTIAL = b"\x1d\x56\x42\x00"     # GS V B 0 - qisman kesish
CUT_FULL = b"\x1d\x56\x41\x00"        # GS V A 0 - to'liq kesish
DRAWER = b"\x1b\x70\x00\x19\xfa"      # ESC p 0 - pul tortmasini ochish (pin 2)
DRAWER_PIN5 = b"\x1b\x70\x01\x19\xfa" # ESC p 1 - pul tortmasini ochish (pin 5)
# Tortma kabeli printer modeliga qarab 2- yoki 5-pinga ulangan bo'ladi.
# Ikkalasiga ham impuls yuboriladi — ulanmagan pin uchun bu hech narsa qilmaydi.
DRAWER_KICK = DRAWER + DRAWER_PIN5


def feed(lines: int) -> bytes:
    """ESC d n — n qator qog'oz surish."""
    lines = max(0, min(int(lines), 255))
    return b"\x1b\x64" + bytes([lines])


def image_to_raster(img: Image.Image, chunk_height: int = 256) -> bytes:
    """PIL rasmni GS v 0 raster bloklariga o'giradi.

    Uzun cheklar bloklab yuboriladi (chunk_height qatordan) — printer buferi
    kichik bo'lsa ham uzilishsiz chiqadi.
    """
    if img.mode != "1":
        gray = img.convert("L")
        # Qora piksel (p < 128) -> 255 -> '1' rejimida 1 bit = chop etiladi
        inverted = gray.point(lambda p: 255 if p < 128 else 0)
        img = inverted.convert("1", dither=Image.Dither.NONE)
    else:
        # '1' rejimida 0=qora; ESC/POS uchun 1=qora bo'lishi kerak -> teskari
        img = img.point(lambda p: 255 - p)

    width_bytes = (img.width + 7) // 8
    xL, xH = width_bytes & 0xFF, (width_bytes >> 8) & 0xFF

    chunk_height = max(1, min(int(chunk_height or 256), 1024))
    out = bytearray()
    for top in range(0, img.height, chunk_height):
        band = img.crop((0, top, img.width, min(top + chunk_height, img.height)))
        h = band.height
        yL, yH = h & 0xFF, (h >> 8) & 0xFF
        out += b"\x1d\x76\x30\x00" + bytes([xL, xH, yL, yH]) + band.tobytes()
    return bytes(out)


def build_receipt(img: Image.Image, *, cut: bool = True, feed_lines: int = 4,
                  drawer: bool = False, chunk_height: int = 256) -> bytes:
    """To'liq chek uchun tayyor ESC/POS bayt oqimi.

    Tartib: init -> chek rasmi -> qog'oz surish -> kesish -> (tortma).
    Tortma impulsi chek to'liq chiqib, kesilgandan KEYIN yuboriladi — chek
    chiqmay qolsa (qog'oz tugagan va h.k.) tortma ham ochilmaydi.
    """
    data = bytearray(INIT)
    data += image_to_raster(img, chunk_height)
    data += feed(feed_lines)
    if cut:
        data += CUT_PARTIAL
    if drawer:
        data += DRAWER_KICK
    return bytes(data)
