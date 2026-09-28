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

## Heroku'ga joylash

Bot `worker` jarayoni sifatida ishlaydi (`Procfile`), ma'lumotlar Heroku Postgres'da saqlanadi.
Heroku fayl tizimi har restartda tozalanadi, shuning uchun SQLite serverda ishlatilmaydi.

```bash
heroku addons:create heroku-postgresql:essential-0 -a slaydcraft   # DATABASE_URL avtomatik qo'shiladi
heroku config:set BOT_TOKEN=... GEMINI_API_KEY=... ADMIN_IDS=... ADMIN_CHAT_ID=... \
    PAYMENT_CARD_NUMBER="8600 ...." PAYMENT_CARD_HOLDER="Ism Familiya" SUPPORT_USERNAME=... -a slaydcraft
git push heroku main
heroku ps:scale web=0 worker=1 -a slaydcraft
heroku logs --tail -a slaydcraft
```

Lokal SQLite ma'lumotlarini Postgres'ga bir marta ko'chirish:

```bash
DATABASE_URL=$(heroku config:get DATABASE_URL -a slaydcraft) python scripts/migrate_sqlite_to_postgres.py
```

Muhim: bot bir vaqtda faqat bitta joyda ishlashi mumkin. Heroku'da ishlayotganda lokal `python main.py`
ishga tushirilmasin (Telegram `Conflict` xatosi beradi).

PDF uchun kirill yozuvini qo'llab-quvvatlaydigan Liberation shriftlari `assets/fonts` da (SIL OFL litsenziyasi).

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
