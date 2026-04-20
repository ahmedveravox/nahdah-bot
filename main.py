"""
نهضة أسيا — Telegram Bot
يشتغل 24/7 على Railway
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv
import database as db
import ai_handler
from scraper import run_full_scrape

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_IDS = set(
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
)

_products_cache: list[dict] = []


async def load_products_cache() -> None:
    global _products_cache
    _products_cache = db.get_all_products(limit=300)
    logger.info(f"Loaded {len(_products_cache)} products into cache")


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _relevant_products(text: str) -> list[dict]:
    if ai_handler.extract_product_query(text):
        searched = db.search_products(text)
        if searched:
            ids = {p["id"] for p in searched}
            rest = [p for p in _products_cache if p["id"] not in ids]
            return searched + rest
    return _products_cache


async def _check_active(user_id: int) -> bool:
    return db.is_client_active(user_id)


async def _register(user) -> None:
    db.upsert_client(user.id, user.username, user.full_name)


# ─── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await _register(user)

    keyboard = [
        [
            InlineKeyboardButton("🛍️ المنتجات",    callback_data="show_products"),
            InlineKeyboardButton("🔍 بحث",         callback_data="search_hint"),
        ],
        [
            InlineKeyboardButton("📞 تواصل معنا",  callback_data="contact"),
            InlineKeyboardButton("🌿 عن المتجر",   callback_data="about"),
        ],
    ]
    await update.message.reply_text(
        f"هلا وغلا يا {user.first_name}! 👋\n"
        "أهلاً بك في عطارة *نهضة أسيا* 🌿\n"
        "متجرك للأعشاب والتوابل والمنتجات الطبيعية الأصيلة.\n\n"
        "كيف أقدر أخدمك اليوم؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ─── /scrape ───────────────────────────────────────────────────────────────────

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر /test — يختبر Gemini ويرجع النتيجة"""
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        await update.message.reply_text("ما عندك صلاحية.")
        return
    await update.message.reply_text("⏳ أختبر Gemini...")
    ok, msg = ai_handler.test_gemini()
    if ok:
        await update.message.reply_text(f"✅ Gemini شغّال!\nالرد: {msg}")
    else:
        await update.message.reply_text(f"❌ Gemini فاشل!\nالخطأ: {msg}\n\nتحقق من GEMINI_API_KEY في Railway Variables.")


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        await update.message.reply_text("ما عندك صلاحية.")
        return
    await update.message.reply_text("⏳ أبدأ سحب المنتجات...")
    try:
        result = run_full_scrape()
        await load_products_cache()
        await update.message.reply_text(
            f"✅ تم!\n📂 الفئات: {result['categories']}\n📦 المنتجات: {result['products']}"
        )
    except Exception as exc:
        logger.error(f"Scrape error: {exc}")
        await update.message.reply_text(f"❌ خطأ: {exc}")


# ─── /products ─────────────────────────────────────────────────────────────────

async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    categories = db.get_categories()
    if not categories:
        await _show_products_list(update.message.reply_text, _products_cache[:15])
        return
    keyboard = _categories_keyboard(categories)
    await update.message.reply_text(
        "اختر الفئة:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


def _categories_keyboard(categories: list[dict]) -> list[list]:
    keyboard, row = [], []
    for i, cat in enumerate(categories):
        row.append(InlineKeyboardButton(
            cat.get("name_ar") or cat.get("name"),
            callback_data=f"cat_{cat['id']}",
        ))
        if len(row) == 2 or i == len(categories) - 1:
            keyboard.append(row)
            row = []
    keyboard.append([InlineKeyboardButton("🛍️ كل المنتجات", callback_data="all_products")])
    return keyboard


async def _show_products_list(reply_fn, products: list[dict]) -> None:
    if not products:
        await reply_fn("ما لقينا منتجات.")
        return
    lines = []
    for p in products[:15]:
        price = f" — {p['price']} ريال" if p.get("price") else ""
        lines.append(f"🌿 *{p.get('name_ar') or p.get('name')}*{price}")
    text = "المنتجات المتاحة:\n\n" + "\n".join(lines)
    if len(products) > 15:
        text += "\n\n_اكتب اسم المنتج للبحث عن المزيد_"
    await reply_fn(text, parse_mode="Markdown")


# ─── Callback Buttons ──────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "show_products":
        cats = db.get_categories()
        if cats:
            await query.edit_message_text(
                "اختر الفئة:", reply_markup=InlineKeyboardMarkup(_categories_keyboard(cats))
            )
        else:
            await _show_products_list(query.edit_message_text, _products_cache[:15])

    elif data.startswith("cat_"):
        products = db.get_products_by_category(int(data.split("_")[1]))
        await _show_products_list(query.edit_message_text, products)

    elif data == "all_products":
        await _show_products_list(query.edit_message_text, _products_cache[:20])

    elif data == "search_hint":
        await query.edit_message_text(
            "🔍 اكتب اسم المنتج اللي تبيه:\n"
            "_مثلاً: هيل، زعتر، حبة البركة، عسل..._",
            parse_mode="Markdown",
        )

    elif data == "contact":
        await query.edit_message_text(
            "📞 *تواصل معنا:*\n\n"
            "🌐 nhdah.com/ar\n"
            "نرد عليك بأسرع وقت 🌿",
            parse_mode="Markdown",
        )

    elif data == "about":
        await query.edit_message_text(
            "🌿 *نهضة أسيا للعطارة*\n\n"
            "متخصصون في الأعشاب الطبيعية والتوابل الأصيلة.\n"
            "جودة عالية وأسعار منافسة 🛍️\n\n"
            "زورونا: nhdah.com",
            parse_mode="Markdown",
        )


# ─── Text Handler ──────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()
    await _register(user)

    if not await _check_active(user.id):
        return

    db.save_message(user.id, "user", text)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    reply = await ai_handler.generate_reply(user.id, text, _relevant_products(text))
    db.save_message(user.id, "assistant", reply)
    await update.message.reply_text(reply)


# ─── Photo Handler ─────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    await _register(user)

    if not await _check_active(user.id):
        return

    caption = update.message.caption or ""
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    try:
        # نجيب أعلى دقة للصورة
        photo   = update.message.photo[-1]
        file    = await context.bot.get_file(photo.file_id)
        img_buf = await file.download_as_bytearray()
        img_bytes = bytes(img_buf)

        db.save_message(user.id, "user", f"[صورة] {caption}".strip())
        reply = await ai_handler.generate_reply_image(
            user.id, img_bytes, caption, _products_cache
        )
    except Exception as exc:
        logger.error(f"Photo handler error: {exc}")
        reply = "وصلت الصورة 📸 — ابعث لي اسم المنتج بالنص وأساعدك! 🌿"

    db.save_message(user.id, "assistant", reply)
    await update.message.reply_text(reply)


# ─── Voice Handler ─────────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await _register(user)

    if not await _check_active(user.id):
        return

    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    try:
        voice     = update.message.voice
        file      = await context.bot.get_file(voice.file_id)
        audio_buf = await file.download_as_bytearray()
        audio_bytes = bytes(audio_buf)

        db.save_message(user.id, "user", "[رسالة صوتية]")
        reply = await ai_handler.generate_reply_voice(
            user.id, audio_bytes, _products_cache
        )
    except Exception as exc:
        logger.error(f"Voice handler error: {exc}")
        reply = "سمعت رسالتك 🎙️ — اكتب طلبك بالنص وأخدمك أحسن! 🌿"

    db.save_message(user.id, "assistant", reply)
    await update.message.reply_text(reply)


# ─── Error Handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update error: {context.error}", exc_info=context.error)


# ─── Main ──────────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    await load_products_cache()
    # تحقق من Gemini عند التشغيل
    ok, msg = ai_handler.test_gemini()
    if ok:
        logger.info(f"✅ Gemini OK: {msg}")
    else:
        logger.error(f"❌ Gemini FAILED: {msg}")


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("scrape",   scrape_command))
    app.add_handler(CommandHandler("test",     test_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO,                   handle_photo))
    app.add_handler(MessageHandler(filters.VOICE,                   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Starting Nahdah Asia Bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
