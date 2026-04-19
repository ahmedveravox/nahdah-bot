"""
نهضة أسيا — Telegram Bot
يشتغل 24/7 على Railway
"""
import os
import logging
import asyncio
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

# كاش المنتجات — نحمّلها مرة وحدة
_products_cache: list[dict] = []


async def load_products_cache() -> None:
    global _products_cache
    _products_cache = db.get_all_products(limit=300)
    logger.info(f"Loaded {len(_products_cache)} products into cache")


# ─── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_client(user.id, user.username, user.full_name)

    keyboard = [
        [
            InlineKeyboardButton("🛍️ المنتجات", callback_data="show_products"),
            InlineKeyboardButton("🔍 بحث", callback_data="search_hint"),
        ],
        [
            InlineKeyboardButton("📞 تواصل معنا", callback_data="contact"),
            InlineKeyboardButton("🌿 عن المتجر", callback_data="about"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome = (
        f"هلا وغلا يا {user.first_name}! 👋\n"
        "أهلاً بك في عطارة **نهضة أسيا** 🌿\n"
        "متجرك للأعشاب والتوابل والمنتجات الطبيعية الأصيلة.\n\n"
        "كيف أقدر أخدمك اليوم؟"
    )
    await update.message.reply_text(welcome, reply_markup=reply_markup, parse_mode="Markdown")


# ─── /scrape (admin) ───────────────────────────────────────────────────────────

ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(",") if os.getenv("ADMIN_IDS") else []))


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        await update.message.reply_text("ما عندك صلاحية لهذا الأمر.")
        return

    await update.message.reply_text("⏳ يا بيت.. أبدأ بسحب المنتجات من الموقع...")
    try:
        result = run_full_scrape(enrich=False)
        await load_products_cache()
        await update.message.reply_text(
            f"✅ تم بنجاح!\n"
            f"📂 الفئات: {result['categories']}\n"
            f"📦 المنتجات: {result['products']}"
        )
    except Exception as exc:
        logger.error(f"Scrape failed: {exc}")
        await update.message.reply_text(f"❌ صار خطأ: {exc}")


# ─── /products ─────────────────────────────────────────────────────────────────

async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _products_cache:
        await update.message.reply_text("ما في منتجات محمّلة حالياً. جرب بعد شوي. 🙏")
        return

    categories = db.get_categories()
    if not categories:
        await _show_flat_products(update, _products_cache[:15])
        return

    keyboard = []
    row = []
    for i, cat in enumerate(categories):
        row.append(InlineKeyboardButton(
            cat.get("name_ar") or cat.get("name"),
            callback_data=f"cat_{cat['id']}"
        ))
        if len(row) == 2 or i == len(categories) - 1:
            keyboard.append(row)
            row = []

    keyboard.append([InlineKeyboardButton("🛍️ كل المنتجات", callback_data="all_products")])
    await update.message.reply_text(
        "اختر الفئة اللي تبيها:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_flat_products(update_or_query, products: list[dict]) -> None:
    if not products:
        text = "ما لقينا منتجات في هذه الفئة."
    else:
        lines = []
        for p in products[:15]:
            price = f" — {p['price']} ريال" if p.get("price") else ""
            lines.append(f"🌿 *{p.get('name_ar') or p.get('name')}*{price}")
        text = "المنتجات المتاحة:\n\n" + "\n".join(lines)
        if len(products) > 15:
            text += f"\n\n_(وأكثر من ذلك... ابحث عن اللي تبيه)_"

    if hasattr(update_or_query, "callback_query"):
        await update_or_query.callback_query.edit_message_text(text, parse_mode="Markdown")
    elif hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update_or_query.message.reply_text(text, parse_mode="Markdown")


# ─── Callback Buttons ──────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "show_products":
        categories = db.get_categories()
        if categories:
            keyboard = []
            row = []
            for i, cat in enumerate(categories):
                row.append(InlineKeyboardButton(
                    cat.get("name_ar") or cat.get("name"),
                    callback_data=f"cat_{cat['id']}"
                ))
                if len(row) == 2 or i == len(categories) - 1:
                    keyboard.append(row)
                    row = []
            keyboard.append([InlineKeyboardButton("🛍️ كل المنتجات", callback_data="all_products")])
            await query.edit_message_text("اختر الفئة:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await _show_flat_products(query, _products_cache[:15])

    elif data.startswith("cat_"):
        cat_id = int(data.split("_")[1])
        products = db.get_products_by_category(cat_id)
        await _show_flat_products(query, products)

    elif data == "all_products":
        await _show_flat_products(query, _products_cache[:20])

    elif data == "search_hint":
        await query.edit_message_text(
            "🔍 فقط اكتب اسم المنتج أو اللي تبي وأنا أساعدك!\n"
            "مثلاً: *هيل، زعتر، حبة البركة، عسل...*",
            parse_mode="Markdown"
        )

    elif data == "contact":
        await query.edit_message_text(
            "📞 **تواصل معنا:**\n\n"
            "🌐 الموقع: https://nhdah.com/ar\n"
            "📧 راسلنا عبر الموقع الرسمي\n\n"
            "نرد عليك بأسرع وقت! 🌿",
            parse_mode="Markdown"
        )

    elif data == "about":
        await query.edit_message_text(
            "🌿 **نهضة أسيا للعطارة**\n\n"
            "متخصصون في الأعشاب الطبيعية والتوابل الأصيلة والمنتجات الصحية.\n"
            "جودة عالية وأسعار منافسة.\n\n"
            "زورونا على: nhdah.com 🛍️",
            parse_mode="Markdown"
        )


# ─── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()

    # تسجيل العميل
    db.upsert_client(user.id, user.username, user.full_name)

    # تحقق من الحساب النشط
    if not db.is_client_active(user.id):
        logger.info(f"Inactive client {user.id} tried to message")
        return  # صامت — ما نرد

    # حفظ رسالة المستخدم
    db.save_message(user.id, "user", text)

    # مؤشر الكتابة
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    # البحث في المنتجات إذا كان في كلمات بحث
    relevant_products = _products_cache
    if ai_handler.extract_product_query(text):
        searched = db.search_products(text)
        if searched:
            relevant_products = searched + [p for p in _products_cache if p not in searched]

    # توليد الرد
    reply = await ai_handler.generate_reply(user.id, text, relevant_products)

    # حفظ رد البوت
    db.save_message(user.id, "assistant", reply)

    await update.message.reply_text(reply)


# ─── Error Handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception: {context.error}", exc_info=context.error)


# ─── Main ──────────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    await load_products_cache()
    logger.info("Bot initialized. Products cache loaded.")


def main() -> None:
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Starting Nahdah Asia Bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
