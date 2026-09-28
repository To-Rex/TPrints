# TPrints — universal chek print xizmati

Kompyuterda fonda ishlaydigan print-server. Boshqa dasturlar (kassa, POS,
veb-sayt, mobil backend) HTTP orqali JSON yuboradi — TPrints chekni chizib,
printerga chiqaradi.

**Asosiy imkoniyatlar:**

- 🖨 **Har qanday printer** — Xprinter va boshqa termal printerlar (ESC/POS),
  hamda oddiy Windows printerlari (GDI) qo'llab-quvvatlanadi
- 📜 **Uzun cheklar** — chek rasm sifatida bloklab yuboriladi, uzunlik chekovi yo'q
- 🎨 **Istalgan dizayn** — matn (o'lcham/qalin/tekislash), jadval, ustunlar,
  QR-kod, shtrix-kod, logo/rasm, ajratuvchi chiziqlar
- 🌐 **Unicode** — lotin, kirill, istalgan til (chek rasm qilib chiqarilgani
  uchun printer kodli sahifalariga bog'liq emas)
- 🔄 **Navbat va qayta urinish** — xatoda avtomatik qayta yuboriladi
- 👁 **Fon rejimi** — tray'da ishlaydi, Windows bilan avtomatik ishga tushadi
- 📄 **PDF / A4 hujjatlar** — tayyor PDF (natija, hisobot) oddiy printerga sahifama-sahifa chiqariladi
- 🔍 **Preview** — chekni chiqarmasdan PNG ko'rinishini olish mumkin
- 🔐 **API kalit** (ixtiyoriy) va CORS (brauzerdan to'g'ridan-to'g'ri ishlaydi)

## O'rnatish

```bash
pip install -r requirements.txt
python main.py
```

Yashirin (fonda) ishga tushirish: `python main.py --minimized`

Sozlamalar oynasida **"Windows bilan birga ishga tushirish"** ni yoqsangiz,
kompyuter yonganda o'zi ishga tushadi.

### EXE qilish (ixtiyoriy)

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name TPrints main.py
```

Tayyor fayl: `dist/TPrints.exe`

## Printerni sozlash

1. **Printerlar** bo'limida printeringizni tanlang
2. **Profil** tugmasi: rejim (`escpos` — termal / `windows` — oddiy),
   qog'oz kengligi (58/80mm), kesish, pul tortmasi
3. **Standart qilish** — dasturlar printer ko'rsatmasa shu ishlatiladi
4. **Sinov cheki** bilan tekshiring

> Xprinter uchun: rejim `escpos`, qog'oz 58 yoki 80mm. Dastur nomiga qarab
> (XP, POS, 58, 80...) buni avtomatik taxmin qiladi.

## Pul tortmasi (cash drawer)

Tortma chek printerining RJ11 portiga ulangan bo'ladi. Ochish uchun uchta yo'l
(birortasi yetarli):

1. **Sozlamalar → Kassa → "Har doim pul tortmasini ochish"** — yoqilsa har bir
   chekdan keyin tortma ochiladi: printer, rejim (`escpos` / `windows` / PDF) va
   so'rovdagi qiymatdan qat'i nazar. Kassa uchun tavsiya etiladigan usul.
2. **Printerlar → Profil → "Pul tortmasini ochish"** — faqat shu printer uchun
   (ikkala rejimda ham ishlaydi).
3. So'rovda `"drawer": true` — faqat shu chek uchun.

**Tortma ulangan printer** (Sozlamalar → Kassa): bir nechta printer bo'lsa
tortma osilgan printerni tanlang — impuls chek qaysi printerga chiqishidan
qat'i nazar doim o'sha printerga boradi. Tanlanmasa impuls chek chiqqan
printerga yuboriladi (lazer/A4 printerga yuborilsa u bir bo'sh sahifa chiqarib
yuborishi mumkin — aralash printerli kassada tanlab qo'ying).

Impuls (`ESC p`, 2- va 5-pin) chek to'liq chiqib, kesilgandan keyin yuboriladi.
`escpos` rejimida chek baytlari oxiriga qo'shiladi, `windows` / PDF rejimida
esa alohida RAW vazifa ("TPrints tortma") sifatida ketadi. Impuls xatosi
chekni "xato" qilmaydi — `/jobs` natijasida `drawer`, `drawer_printer`,
`drawer_error` maydonlari ko'rinadi.

## API

Standart manzil: `http://127.0.0.1:9100`

| Metod | Yo'l | Vazifasi |
|-------|------|----------|
| GET | `/` | Holat |
| GET | `/printers` | Printerlar ro'yxati |
| GET | `/jobs`, `/jobs/<id>` | Vazifalar tarixi/holati |
| POST | `/print` | Chek chiqarish (asosiy) |
| POST | `/print/text` | Oddiy matn |
| POST | `/print/image` | Rasm (base64) |
| POST | `/print/pdf` | PDF hujjat (A4, base64) — oddiy/lazer printerga |
| POST | `/preview/pdf` | PDF sahifasini PNG sifatida qaytaradi (chiqarmaydi) |
| POST | `/print/raw` | Tayyor ESC/POS baytlar (base64) |
| POST | `/preview` | Chekni PNG sifatida qaytaradi (chiqarmaydi) |
| POST | `/test` | Sinov cheki |

API kalit o'rnatilgan bo'lsa har bir so'rovga `X-API-Key` sarlavhasi qo'shiladi.

### POST /print — asosiy maydonlar

```jsonc
{
  "printer": "XP-80C",   // ixtiyoriy; bo'lmasa standart printer
  "copies": 2,            // nusxalar soni (1..20)
  "cut": true,            // profildagini vaqtincha almashtiradi (ixtiyoriy)
  "drawer": false,        // pul tortmasi (ixtiyoriy)
  "paper": 80,            // 58 yoki 80 (ixtiyoriy)
  "wait": true,           // true -> chop etilgunча javob kutadi
  "elements": [ ... ]     // chek dizayni (quyida)
}
```

### Elementlar

```jsonc
[
  {"type": "title",  "value": "DO'KON NOMI", "size": 3},
  {"type": "text",   "value": "Manzil...", "align": "center",
   "bold": false, "size": 1, "mono": false, "underline": false},
  {"type": "line"},                          // chiziq
  {"type": "line",   "char": "=", "style": "dashed"},
  {"type": "row",    "left": "Jami:", "right": "45 000", "bold": true, "size": 2},
  {"type": "columns", "cols": [
      {"text": "A", "width": 2, "align": "left"},
      {"text": "B", "width": 1, "align": "right"}]},
  {"type": "table",
   "headers": ["Mahsulot", "Soni", "Narx"],
   "widths":  [3, 1, 2],
   "aligns":  ["left", "center", "right"],
   "rows": [["Osh", "1", "35 000"], ["Non", "2", "8 000"]]},
  {"type": "image",  "base64": "iVBOR...", "width_pct": 50, "align": "center"},
  {"type": "qr",     "value": "https://...", "size": 6},
  {"type": "barcode", "value": "123456789012", "kind": "code128", "height": 80},
  {"type": "feed",   "lines": 2},
  {"type": "space",  "px": 20}
]
```

`size`: 1=oddiy, 2=katta, 3=juda katta, 4=ulkan. Aniq o'lcham kerak bo'lsa
`font_size` (piksel) ishlating. Matn sig'masa avtomatik keyingi qatorga o'tadi.

### Misollar

**Python:**
```python
import requests
requests.post("http://127.0.0.1:9100/print", json={
    "elements": [
        {"type": "title", "value": "Salom!"},
        {"type": "row", "left": "Jami:", "right": "10 000 so'm", "bold": True},
    ]
})
```

**JavaScript (brauzer/Electron):**
```js
fetch("http://127.0.0.1:9100/print", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    elements: [{type: "title", value: "Salom!"}]
  })
});
```

**curl:**
```bash
curl -X POST http://127.0.0.1:9100/print/text -H "Content-Type: application/json" -d "{\"text\": \"Salom dunyo!\"}"
```

**To'liq demo:** `python test_client.py` (server ishlab turganda) yoki
`python test_client.py --preview chek.png` — chiqarmasdan rasmini ko'rish.

## PDF / A4 hujjat chop etish

Tayyor PDF (masalan, tasdiqlangan tahlil natijasi) oddiy printerga chiqariladi.
Printer profili `windows` rejimida bo'lishi kerak (termal chek printeriga A4 chiqmaydi).
Sahifalar PyMuPDF bilan rasmga aylantirilib, sahifaga sig'dirilgan holda chiqariladi.

```jsonc
POST /print/pdf
{
  "pdf_base64": "JVBERi0xLjQ...",   // PDF fayl (base64)
  "printer": "HP LaserJet",         // ixtiyoriy; bo'lmasa standart printer
  "copies": 1,
  "doc_name": "Natija UR-000123",    // Windows navbatida ko'rinadigan nom
  "dpi": 200,                        // render sifati (72..300)
  "wait": true
}
```

`POST /preview/pdf` (`pdf_base64`, `page`, `dpi`) — chiqarmasdan bitta sahifani PNG qilib qaytaradi.

## Tarmoq orqali (boshqa kompyuterdan)

Sozlamalarda manzilni `0.0.0.0` qiling va API kalit o'rnating. Boshqa
qurilmalar `http://<kompyuter-IP>:9100` ga yuboradi. Windows Firewall
so'rasa ruxsat bering.

## Muammolar

- **Chek chiqmayapti, xato ham yo'q** — Windows'da printer navbatini tekshiring;
  printer "Offline" bo'lsa Windows uni navbatda saqlaydi.
- **58mm printerda chek qirqilib chiqyapti** — profildagi qog'ozni 58 qiling
  (standart 80).
- **Pul tortmasi ochilmayapti** — Sozlamalar → Kassa da "Har doim pul tortmasini
  ochish" ni yoqing, bir nechta printer bo'lsa "Tortma ulangan printer" ni
  tanlang, **Saqlash** ni bosing va "Sinov cheki" chiqaring. `/jobs` da oxirgi
  vazifaning `drawer` / `drawer_error` maydonlarini qarang. Tortma kabeli
  printerga (kompyuterga emas) ulanganini tekshiring. Printer ESC/POS tilini
  tushunmasa (masalan Star) `ESC p` impulsi unga ta'sir qilmaydi.
- **Port band** — Sozlamalarda boshqa port tanlang (masalan 9101).
- Loglar: `%APPDATA%\TPrints\logs\tprints.log`
