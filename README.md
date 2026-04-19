# نهضة أسيا — Telegram Bot 🌿

بوت تلغرام احترافي لعطارة نهضة أسيا، يرد بالعربي بلهجة سعودية خليجية.

## الملفات

```
nahdah-bot/
├── main.py          # البوت الرئيسي
├── scraper.py       # سحب المنتجات من nhdah.com
├── database.py      # Supabase client
├── ai_handler.py    # Gemini AI للردود
├── requirements.txt
├── railway.json     # إعدادات Railway
├── Procfile
└── sql/schema.sql   # جداول قاعدة البيانات
```

## خطوات الإعداد

### 1. إنشاء جداول Supabase
افتح Supabase → SQL Editor وشغّل:
```sql
-- انسخ محتوى sql/schema.sql وشغّله هنا
```

### 2. متغيرات البيئة
انسخ `.env.example` إلى `.env` وضع المفاتيح:
```
TELEGRAM_TOKEN=...
GEMINI_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
ADMIN_IDS=123456789  # Telegram ID تبعك (اختياري)
```

### 3. تشغيل محلي
```bash
pip install -r requirements.txt
python main.py
```

### 4. سحب المنتجات
```bash
python scraper.py
```
أو أرسل `/scrape` للبوت لو عندك ADMIN_IDS.

### 5. الرفع على Railway
1. ارفع المجلد على GitHub repo منفصل
2. افتح [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. أضف متغيرات البيئة في Settings → Variables
4. Deploy!

## أوامر البوت

| الأمر | الوصف |
|-------|-------|
| `/start` | بداية المحادثة |
| `/products` | عرض المنتجات |
| `/scrape` | تحديث المنتجات (أدمن فقط) |

## إيقاف عميل

في Supabase → Table Editor → clients → غيّر `active` إلى `false`.
البوت يوقف الرد فوراً بدون إشعار.
