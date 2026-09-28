# SlideCraft AI — Telegram Mini App

Vue 3 + Vite + TypeScript + Tailwind CSS v4 + Pinia + Lucide.

```bash
npm install
npm run dev        # http://localhost:5173 (VITE_API_URL bo'sh bo'lsa demo rejim)
npm run build      # dist/ — istalgan statik hostingga (Vercel, Netlify, Cloudflare Pages)
```

`.env.example` dan `.env` yarating:

- `VITE_API_URL` — backend API manzili. Bo'sh bo'lsa ilova demo (mock) rejimda ishlaydi.
- `VITE_BOT_USERNAME` — bot username'i (`slaydreferat_aibot`).

## Backend API shartnomasi

Har bir so'rovda `Authorization: tma <initData>` sarlavhasi yuboriladi. Backend `initData`
imzosini bot tokeni bilan tekshirishi shart (Telegram hujjatlari: "Validating data received via the Mini App").

| Metod | Yo'l | Javob |
| --- | --- | --- |
| GET | `/me` | `Profile` |
| GET | `/tariffs` | `Tariff[]` |
| GET | `/history?limit=20` | `HistoryItem[]` |
| POST | `/jobs` | `Job` (kredit yo'q bo'lsa `402`) |
| GET | `/jobs/:id` | `Job` |
| POST | `/files/:id/send` | `{ ok: true }` |
| POST | `/payments` | `PaymentLink` |

Tiplar: `src/types/index.ts`.

## Botga ulash

BotFather → `/mybots` → bot → **Bot Settings → Menu Button** (yoki **Configure Mini App**)
→ `dist/` joylashgan HTTPS manzilni kiriting.
