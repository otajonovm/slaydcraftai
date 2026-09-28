# SlideCraft AI — Telegram bot (@slaydreferat_aibot)

Google Gemini yordamida **taqdimot** (PowerPoint `.pptx` + `.pdf`) va **referat / mustaqil ish**
(Word `.docx` + `.pdf`) tayyorlovchi Telegram bot.

## Imkoniyatlar

- **Taqdimot**: mavzu, slaydlar soni (8/10/12/15), til (uz/ru/en), dizayn (Minimal White, Modern Blue, Dark Tech).
  16:9 format, kartochkali zamonaviy dizayn, maxsus titul va xulosa slaydlari, taqqoslash va iqtibos slaydlari,
  har bir slaydda ma'ruzachi izohlari (speaker notes).
- **Referat / mustaqil ish**: OTM standarti bo'yicha titul varag'i (vazirlik, muassasa, mavzu, Bajardi/Qabul qildi,
  shahar va yil), reja, kirish, 2 bob va fasllar, xulosa, adabiyotlar ro'yxati.
  Times New Roman 14 pt (sarlavhalar 16 pt qalin), 1.5 interval, hoshiyalar 3 / 1.5 / 2 / 2 sm,
  sahifa raqami pastda markazda (titulda ko'rinmaydi).
- **PDF**: LibreOffice o'rnatilgan bo'lsa u orqali, aks holda reportlab bilan (kirill yozuvi qo'llab-quvvatlanadi).
- Og'ir ishlar `asyncio.to_thread()` da, Gemini so'rovlari asinxron; status xabarlari va `upload_document` action.
- SQLite bazasi: foydalanuvchilar, generatsiyalar tarixi, kunlik limit, `/stats` (adminlar uchun).

## O'rnatish

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # va qiymatlarni to'ldiring
python main.py
```

### .env sozlamalari

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather tokeni |
| `GEMINI_API_KEY` | Google AI Studio kaliti |
| `GEMINI_MODEL` | Asosiy model (standart `gemini-3.8-flash`) |
| `GEMINI_FALLBACK_MODELS` | Asosiy model ishlamasa navbatdagi modellar |
| `ADMIN_IDS` | `/stats` ko'ra oladigan Telegram ID lar |
| `DAILY_LIMIT` | Kunlik limit (0 = cheksiz, adminlarga limit yo'q) |
| `MAX_CONCURRENT_JOBS` | Bir vaqtdagi generatsiyalar soni |
| `LIBREOFFICE_PATH` | `soffice` yo'li (ixtiyoriy) |

### Serverda (Linux) yuqori sifatli PDF uchun

```bash
sudo apt install -y libreoffice-impress libreoffice-writer fonts-liberation fonts-dejavu
```

## Tuzilma

```
main.py                    # ishga tushirish nuqtasi
config.py                  # .env sozlamalari
database/                  # aiosqlite: users, generations
bot/handlers/              # common, presentation (FSM), referat (FSM)
bot/keyboards/             # inline va reply tugmalar
bot/states/                # FSM holatlari
services/gemini_service.py # Gemini (structured JSON)
services/pptx_generator.py # python-pptx 16:9 dizayn
services/docx_generator.py # python-docx akademik referat
services/pdf_converter.py  # LibreOffice / reportlab PDF
```
