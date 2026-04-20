"""
Gemini AI handler — ردود باللهجة السعودية + دعم الصور والصوت
"""
import os
import io
import base64
import logging
import google.generativeai as genai
from dotenv import load_dotenv
import database as db

load_dotenv()
logger = logging.getLogger(__name__)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_KEY)

GENERATION_CONFIG = {
    "temperature": 0.7,
    "max_output_tokens": 350,
}

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

SYSTEM_PROMPT = """أنت مساعد ذكي لعطارة "نهضة أسيا" للأعشاب والتوابل والمنتجات الطبيعية.

قواعد صارمة:
- اللهجة سعودية خليجية ودية دايماً
- الرد قصير ومباشر: جملتين أو ثلاث بحد أقصى
- اقترح المنتج المناسب من القائمة مع ذكر السعر
- لو ما في منتج محدد، اقترح الأقرب إليه
- الموقع للطلب: nhdah.com

المنتجات المتاحة:
{products_context}
"""


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_model(vision: bool = False) -> genai.GenerativeModel:
    name = "gemini-1.5-flash" if vision else "gemini-1.5-flash"
    return genai.GenerativeModel(
        model_name=name,
        generation_config=GENERATION_CONFIG,
        safety_settings=SAFETY_SETTINGS,
    )


def _products_context(products: list[dict]) -> str:
    if not products:
        return "لا يوجد منتجات محمّلة حالياً."
    lines = []
    for p in products[:60]:
        cat = ""
        if isinstance(p.get("categories"), dict):
            cat = f" [{p['categories'].get('name_ar', '')}]"
        price = f" - {p['price']} ريال" if p.get("price") else ""
        lines.append(f"• {p.get('name_ar') or p.get('name', '')}{cat}{price}")
    return "\n".join(lines)


def _history_text(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for msg in history[-6:]:
        prefix = "عميل" if msg["role"] == "user" else "بوت"
        lines.append(f"{prefix}: {msg['message']}")
    return "\n".join(lines) + "\n"


def _build_prompt(user_message: str, products: list[dict], history: list[dict]) -> str:
    system = SYSTEM_PROMPT.format(products_context=_products_context(products))
    hist   = _history_text(history)
    return f"{system}\n\n{hist}عميل: {user_message}\nبوت:"


def _safe_text(response) -> str:
    try:
        text = response.text.strip()
        return text if text else ""
    except Exception:
        return ""


# ─── Public API ────────────────────────────────────────────────────────────────

async def generate_reply(user_id: int, user_message: str, products: list[dict]) -> str:
    """رد على رسالة نصية"""
    history = db.get_conversation_history(user_id, limit=8)
    prompt  = _build_prompt(user_message, products, history)
    try:
        model    = _get_model()
        response = model.generate_content(prompt)
        text     = _safe_text(response)
        if text:
            return text
        raise ValueError("empty response")
    except Exception as exc:
        logger.error(f"Gemini text error: {exc}")
        return _fallback_reply(user_message, products)


async def generate_reply_image(user_id: int, image_bytes: bytes, caption: str, products: list[dict]) -> str:
    """يفهم الصورة ويرد — العميل يرسل صورة منتج"""
    history = db.get_conversation_history(user_id, limit=4)
    system  = SYSTEM_PROMPT.format(products_context=_products_context(products))
    hist    = _history_text(history)

    prompt_text = (
        f"{system}\n\n{hist}"
        f"العميل أرسل صورة"
        f"{' مع تعليق: ' + caption if caption else '.'}\n"
        f"حدّد المنتج في الصورة إذا كان من منتجاتنا، أو اقترح الأنسب. بوت:"
    )

    try:
        # نحوّل الصورة لـ base64 ونرسلها لـ Gemini Vision
        img_b64  = base64.b64encode(image_bytes).decode()
        img_part = {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
        model    = _get_model(vision=True)
        response = model.generate_content([prompt_text, img_part])
        text     = _safe_text(response)
        if text:
            return text
        raise ValueError("empty vision response")
    except Exception as exc:
        logger.error(f"Gemini image error: {exc}")
        return "وصلت الصورة 📸 — ابعث لي اسم المنتج اللي تبيه وأساعدك أكثر! 🌿"


async def generate_reply_voice(user_id: int, audio_bytes: bytes, products: list[dict]) -> str:
    """يفهم الرسالة الصوتية ويرد"""
    history = db.get_conversation_history(user_id, limit=4)
    system  = SYSTEM_PROMPT.format(products_context=_products_context(products))
    hist    = _history_text(history)

    prompt_text = (
        f"{system}\n\n{hist}"
        f"العميل أرسل رسالة صوتية. اسمعها وحدّد طلبه وارد عليه باللهجة السعودية. بوت:"
    )

    try:
        audio_b64  = base64.b64encode(audio_bytes).decode()
        audio_part = {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}}
        model      = _get_model(vision=True)  # gemini-1.5-flash يدعم الصوت أيضاً
        response   = model.generate_content([prompt_text, audio_part])
        text       = _safe_text(response)
        if text:
            return text
        raise ValueError("empty audio response")
    except Exception as exc:
        logger.error(f"Gemini voice error: {exc}")
        return "سمعت رسالتك الصوتية 🎙️ — ممكن تكتب طلبك بالنص عشان أخدمك أحسن! 🌿"


# ─── Fallback ──────────────────────────────────────────────────────────────────

def _fallback_reply(message: str, products: list[dict]) -> str:
    words = message.lower().split()
    for p in products:
        name = (p.get("name_ar") or p.get("name", "")).lower()
        if any(w in name for w in words):
            price = f" بسعر {p['price']} ريال" if p.get("price") else ""
            return f"عندنا {p.get('name_ar') or p.get('name', '')}{price} 🌿 تقدر تطلب من nhdah.com"
    return "هلا! اكتب اسم المنتج اللي تبيه وأنا أدلّك 🌿"


def extract_product_query(message: str) -> bool:
    keywords = [
        "أبي","ابي","أريد","اريد","بكم","كم سعر","كم ثمن",
        "ما سعر","هل عندكم","عندكم","يوجد","دواء","علاج",
        "توابل","أعشاب","زعتر","كمون","هيل","عسل","زيت",
    ]
    return any(kw in message for kw in keywords)
