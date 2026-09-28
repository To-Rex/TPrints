"""TPrints API dan foydalanish namunasi — mijoz dastur shunday chek yuboradi.

Ishlatish:
  python test_client.py                    # to'liq demo chekni chiqarish
  python test_client.py --preview out.png  # chiqarmasdan PNG ko'rinishini olish
  python test_client.py --long             # juda uzun chek (50 mahsulot) sinovi
  python test_client.py --printer "XP-80C" # aniq printerga
  python test_client.py --pdf natija.pdf    # PDF hujjatni (A4) chiqarish
  python test_client.py --pdf natija.pdf --preview p1.png  # 1-sahifani PNG qilish
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:9100"


def post(path: str, payload: dict, out_file: str = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        # API kalit o'rnatilgan bo'lsa: headers={"X-API-Key": "kalit..."}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        print(f"Server xatosi ({e.code}):")
        try:
            print(json.dumps(json.loads(e.read()), ensure_ascii=False, indent=2))
        except Exception:
            pass
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"TPrints serveriga ulanib bo'lmadi: {BASE}")
        print("Avval dasturni ishga tushiring:  python main.py")
        print("(yoki tray'da ishlayotganini va portni tekshiring)")
        print(f"Texnik sabab: {e.reason}")
        sys.exit(1)
    if out_file:
        with open(out_file, "wb") as f:
            f.write(body)
        print(f"Saqlandi: {out_file} ({len(body)} bayt)")
    else:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))


def demo_receipt(printer=None, long=False):
    items = [
        ["Osh (katta)", "1", "40 000"],
        ["Shashlik (mol)", "3", "54 000"],
        ["Non", "2", "8 000"],
        ["Choy (ko'k)", "1", "5 000"],
        ["Salat \"Achichuq\"", "1", "12 000"],
    ]
    if long:
        items = [[f"Mahsulot №{i+1} (uzun nomli sinov)", str(i % 5 + 1),
                  f"{(i * 3711) % 90000 + 5000:,}".replace(",", " ")]
                 for i in range(50)]

    return {
        "printer": printer,          # None -> standart printer
        "copies": 1,
        "cut": True,                 # profil sozlamasini vaqtincha almashtirish
        "wait": True,                # javob chop etib bo'lingach qaytadi
        "elements": [
            {"type": "title", "value": "OSH MARKAZI", "size": 3},
            {"type": "text", "value": "Toshkent sh., Chilonzor t., 45-uy",
             "align": "center"},
            {"type": "text", "value": "Tel: +998 90 123 45 67", "align": "center"},
            {"type": "line", "char": "="},
            {"type": "row", "left": "Chek №:", "right": "000123"},
            {"type": "row", "left": "Kassir:", "right": "Aziza"},
            {"type": "row", "left": "Sana:", "right": "30.07.2026 12:45"},
            {"type": "line"},
            {"type": "table",
             "headers": ["Mahsulot", "Soni", "Summa"],
             "widths": [3, 1, 2],
             "aligns": ["left", "center", "right"],
             "rows": items},
            {"type": "line", "char": "-"},
            {"type": "row", "left": "Jami:", "right": "119 000 so'm", "size": 2,
             "bold": True},
            {"type": "row", "left": "Naqd:", "right": "120 000 so'm"},
            {"type": "row", "left": "Qaytim:", "right": "1 000 so'm"},
            {"type": "line", "char": "="},
            {"type": "qr", "value": "https://soliq.uz/check?id=000123", "size": 5},
            {"type": "text", "value": "Fiskal chek • soliq.uz", "align": "center",
             "font_size": 18},
            {"type": "barcode", "value": "4780000123456", "kind": "code128",
             "height": 70},
            {"type": "feed", "lines": 1},
            {"type": "text", "value": "XARIDINGIZ UCHUN RAHMAT!",
             "align": "center", "bold": True},
        ],
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    printer = None
    if "--printer" in args:
        printer = args[args.index("--printer") + 1]
    if "--pdf" in args:
        import base64
        with open(args[args.index("--pdf") + 1], "rb") as f:
            pdf_payload = {"printer": printer, "copies": 1, "wait": True,
                           "doc_name": "TPrints sinov hujjati",
                           "pdf_base64": base64.b64encode(f.read()).decode("ascii")}
        if "--preview" in args:
            post("/preview/pdf", pdf_payload, out_file=args[args.index("--preview") + 1])
        else:
            post("/print/pdf", pdf_payload)
        sys.exit(0)

    payload = demo_receipt(printer, long="--long" in args)

    if "--preview" in args:
        out = args[args.index("--preview") + 1]
        post("/preview", payload, out_file=out)
    else:
        post("/print", payload)
