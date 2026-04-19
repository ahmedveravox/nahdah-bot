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
model = genai.GenerativeModel("gemini-1.5-flash")

SYSTEM_PROMPT = """أنت مساعد بوت تلغرام لعطارة "نهضة أسيا" — متخصصين في الأعشاب والتوابل والمنتجات الطبيعية.

قواعد ثابتة:
- تكلم باللهجة السعودية الخليجية الودية دايماً
- ردودك قصيرة ومباشرة (2-3 جمل بحد أقصى)
- إذا العميل يسأل عن منتج، ابحث في المنتجات المتاحة واقترح الأنسب
- لما تعرض منتجات، ذكر الاسم والسعر بشكل واضح
- إذا ما في منتج محدد، اقترح البديل القريب
- لا تتكلم في مواضيع خارج العطارة والمنتجات الطبيعية
- للطلب أو الاستفسار، وجّه العميل للتواصل المباشر

المنتجات المتاحة (من الموقع):
{products_context}
"""


def _build_products_context(products: list[dict]) -> str:
    if not products:
        return "لا يوجد منتجات محمّلة حالياً."
    lines = []
    for p in products[:80]:  # نحدد بـ 80 منتج عشان ما تطول كثير
        cat = ""
        if p.get("categories"):
            cat = f" [{p['categories'].get('name_ar', '')}]"
        price = f" - {p['price']} ريال" if p.get("price") else ""
        lines.append(f"• {p.get('name_ar') or p.get('name', '')}{cat}{price}")
    return "\n".join(lines)


def _build_history(history: list[dict]) -> list[dict]:
    gemini_history = []
    for msg in history[:-1]:  # آخر رسالة راح نرسلها كـ user turn
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({
            "role": role,
            "parts": [msg["message"]],
        })
    return gemini_history


async def generate_reply(
    user_id: int,
    user_message: str,
    products: list[dict],
) -> str:
    history = db.get_conversation_history(user_id, limit=10)
    products_context = _build_products_context(products)
    system = SYSTEM_PROMPT.format(products_context=products_context)

    try:
        # نبني المحادثة مع السياق
        chat = model.start_chat(history=_build_history(history))

        # نضيف السيستم برومبت في أول رسالة لو ما في تاريخ
        if not history:
            full_message = f"{system}\n\n---\nرسالة العميل: {user_message}"
        else:
            full_message = user_message

        response = chat.send_message(full_message)
        return response.text.strip()

    except Exception as exc:
        logger.error(f"Gemini error: {exc}")
        return "عذراً، صار خلل بسيط. حاول مرة ثانية بعد شوي. 🙏"


def extract_product_query(message: str) -> str | None:
    """يستخرج اسم المنتج أو الفئة المطلوبة من رسالة العميل"""
    keywords = [
        "أبي", "ابي", "أريد", "اريد", "أطلب", "اطلب",
        "عندكم", "عندكم", "يوجد", "في", "بكم", "كم سعر",
        "كم ثمن", "ما سعر", "هل عندكم", "دواء", "علاج",
        "توابل", "أعشاب", "زعتر", "كمون", "هيل",
    ]
    msg_lower = message.lower()
    for kw in keywords:
        if kw in msg_lower:
            return message
    return None
