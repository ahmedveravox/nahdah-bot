"""
Gemini AI handler — يولّد ردود باللهجة السعودية
"""
import os
import logging
import google.generativeai as genai
from dotenv import load_dotenv
import database as db

load_dotenv()
logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# نجرب أكثر من موديل — نبدأ بالأحدث
MODELS_FALLBACK = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-pro",
]

SYSTEM_PROMPT = """أنت مساعد بوت تلغرام لعطارة "نهضة أسيا" — متخصصين في الأعشاب والتوابل والمنتجات الطبيعية.

قواعد ثابتة:
- تكلم باللهجة السعودية الخليجية الودية دايماً
- ردودك قصيرة ومباشرة (2-3 جمل بحد أقصى)
- إذا العميل يسأل عن منتج، ابحث في المنتجات المتاحة واقترح الأنسب
- لما تعرض منتجات، ذكر الاسم والسعر بشكل واضح
- إذا ما في منتج محدد، اقترح البديل القريب
- لا تتكلم في مواضيع خارج العطارة والمنتجات الطبيعية
- للطلب أو الاستفسار، وجّه العميل للتواصل عبر الموقع nhdah.com

المنتجات المتاحة:
{products_context}
"""


def _build_products_context(products: list[dict]) -> str:
    if not products:
        return "لا يوجد منتجات محمّلة حالياً."
    lines = []
    for p in products[:60]:
        cat = ""
        if p.get("categories") and isinstance(p["categories"], dict):
            cat = f" [{p['categories'].get('name_ar', '')}]"
        price = f" - {p['price']} ريال" if p.get("price") else ""
        name = p.get("name_ar") or p.get("name", "")
        lines.append(f"• {name}{cat}{price}")
    return "\n".join(lines)


def _get_model():
    """يحاول يجيب موديل شغّال"""
    for model_name in MODELS_FALLBACK:
        try:
            m = genai.GenerativeModel(
                model_name=model_name,
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 300,
                },
            )
            return m
        except Exception as exc:
            logger.warning(f"Model {model_name} failed: {exc}")
    return None


async def generate_reply(
    user_id: int,
    user_message: str,
    products: list[dict],
) -> str:
    history = db.get_conversation_history(user_id, limit=8)
    products_context = _build_products_context(products)
    system = SYSTEM_PROMPT.format(products_context=products_context)

    # نبني prompt مع السياق الكامل بدون chat history
    # (أبسط وأضمن مع الـ anon key)
    history_text = ""
    if history:
        lines = []
        for msg in history[-6:]:
            prefix = "عميل" if msg["role"] == "user" else "بوت"
            lines.append(f"{prefix}: {msg['message']}")
        history_text = "\n".join(lines) + "\n"

    prompt = (
        f"{system}\n\n"
        f"{'سياق المحادثة السابقة:' + chr(10) + history_text if history_text else ''}"
        f"عميل: {user_message}\n"
        f"بوت:"
    )

    try:
        model = _get_model()
        if not model:
            raise ValueError("No available Gemini model")

        response = model.generate_content(prompt)
        text = response.text.strip() if response.text else ""
        if not text:
            raise ValueError("Empty response from Gemini")
        return text

    except Exception as exc:
        logger.error(f"Gemini error: {exc}")
        # رد احتياطي بدون AI
        return _fallback_reply(user_message, products)


def _fallback_reply(message: str, products: list[dict]) -> str:
    """رد بسيط بدون AI لو فشل Gemini"""
    searched = [
        p for p in products
        if any(w in (p.get("name_ar") or p.get("name", "")).lower()
               for w in message.lower().split())
    ]
    if searched:
        p = searched[0]
        name = p.get("name_ar") or p.get("name", "")
        price = f" بسعر {p['price']} ريال" if p.get("price") else ""
        return f"عندنا {name}{price} 🌿 تبي تطلب؟ تواصل معنا على nhdah.com"
    return "هلا! كيف أقدر أساعدك؟ اكتب اسم المنتج اللي تبيه وأنا أدلّك 🌿"


def extract_product_query(message: str) -> str | None:
    """يستخرج اسم المنتج أو الفئة المطلوبة من رسالة العميل"""
    keywords = [
        "أبي", "ابي", "أريد", "اريد", "أطلب", "اطلب",
        "عندكم", "يوجد", "بكم", "كم سعر", "كم ثمن",
        "ما سعر", "هل عندكم", "دواء", "علاج",
        "توابل", "أعشاب", "زعتر", "كمون", "هيل",
    ]
    msg_lower = message.lower()
    for kw in keywords:
        if kw in msg_lower:
            return message
    return None
