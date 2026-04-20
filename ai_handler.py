"""
Gemini AI handler — REST API مباشر بدون library
"""
import os
import base64
import logging
import requests
from dotenv import load_dotenv
import database as db

load_dotenv()
logger = logging.getLogger(__name__)

GEMINI_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
HEADERS     = {"Content-Type": "application/json"}

SYSTEM_PROMPT = """أنت موظف خدمة عملاء في عطارة "نهضة أسيا" للأعشاب والتوابل والمنتجات الطبيعية.

تعليمات:
- تحكي باللهجة السعودية الخليجية الودية
- ردودك قصيرة 2-3 جمل بس
- رحّب بالعميل بحرارة عند أول رسالة
- إذا سأل عن منتج اقترح الأنسب من القائمة مع السعر
- إذا ما عندنا المنتج اقترح البديل الأقرب
- للطلب وجّهه لـ nhdah.com
- لا تتكلم في مواضيع ثانية غير العطارة والمنتجات

قائمة المنتجات المتاحة:
{products_context}
"""


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _products_context(products: list[dict]) -> str:
    if not products:
        return "لا توجد منتجات محمّلة."
    lines = []
    for p in products[:70]:
        cat   = ""
        if isinstance(p.get("categories"), dict):
            cat = f" [{p['categories'].get('name_ar', '')}]"
        price = f" - {p['price']} ريال" if p.get("price") else ""
        lines.append(f"• {p.get('name_ar') or p.get('name', '')}{cat}{price}")
    return "\n".join(lines)


def _history_lines(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for msg in history[-6:]:
        role = "عميل" if msg["role"] == "user" else "أنت"
        lines.append(f"{role}: {msg['message']}")
    return "\n".join(lines)


def _call_gemini(parts: list[dict]) -> str:
    """استدعاء Gemini REST API مباشر"""
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 300,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    try:
        resp = requests.post(
            GEMINI_URL,
            headers=HEADERS,
            params={"key": GEMINI_KEY},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        # استخرج النص من الرد
        candidates = data.get("candidates", [])
        if not candidates:
            logger.error(f"Gemini no candidates: {data}")
            return ""

        content = candidates[0].get("content", {})
        parts_out = content.get("parts", [])
        if not parts_out:
            logger.error(f"Gemini empty parts: {data}")
            return ""

        text = parts_out[0].get("text", "").strip()
        logger.info(f"Gemini OK — {len(text)} chars")
        return text

    except requests.HTTPError as exc:
        logger.error(f"Gemini HTTP error {exc.response.status_code}: {exc.response.text}")
        return ""
    except Exception as exc:
        logger.error(f"Gemini call failed: {exc}")
        return ""


# ─── Public API ────────────────────────────────────────────────────────────────

async def generate_reply(user_id: int, user_message: str, products: list[dict]) -> str:
    history  = db.get_conversation_history(user_id, limit=8)
    system   = SYSTEM_PROMPT.format(products_context=_products_context(products))
    hist_txt = _history_lines(history)

    prompt = (
        f"{system}\n\n"
        f"{'سياق المحادثة:\n' + hist_txt + chr(10) if hist_txt else ''}"
        f"عميل: {user_message}\n"
        f"ردك:"
    )

    text = _call_gemini([{"text": prompt}])
    if text:
        return text

    logger.warning("Gemini failed — using fallback")
    return _fallback_reply(user_message, products)


async def generate_reply_image(
    user_id: int, image_bytes: bytes, caption: str, products: list[dict]
) -> str:
    system = SYSTEM_PROMPT.format(products_context=_products_context(products))
    prompt = (
        f"{system}\n\n"
        f"العميل أرسل صورة{' مع تعليق: ' + caption if caption else '.'}\n"
        f"حدّد إذا كان المنتج في الصورة موجود عندنا أو اقترح الأنسب. ردك:"
    )

    img_b64 = base64.b64encode(image_bytes).decode()
    parts   = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
    ]

    text = _call_gemini(parts)
    return text if text else "وصلت الصورة 📸 — اكتب اسم المنتج وأساعدك! 🌿"


async def generate_reply_voice(
    user_id: int, audio_bytes: bytes, products: list[dict]
) -> str:
    system    = SYSTEM_PROMPT.format(products_context=_products_context(products))
    prompt    = (
        f"{system}\n\n"
        f"العميل أرسل رسالة صوتية. اسمع وحدّد طلبه وارد باللهجة السعودية. ردك:"
    )
    audio_b64 = base64.b64encode(audio_bytes).decode()
    parts     = [
        {"text": prompt},
        {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}},
    ]

    text = _call_gemini(parts)
    return text if text else "سمعت رسالتك 🎙️ — اكتب طلبك بالنص وأخدمك! 🌿"


# ─── Fallback ──────────────────────────────────────────────────────────────────

def _fallback_reply(message: str, products: list[dict]) -> str:
    words = message.split()
    for p in products:
        name = (p.get("name_ar") or p.get("name", ""))
        if any(w in name for w in words):
            price = f" بسعر {p['price']} ريال" if p.get("price") else ""
            return f"عندنا {name}{price} 🌿 تقدر تطلب من nhdah.com"
    return "هلا! كيف أقدر أخدمك؟ اكتب المنتج اللي تبيه 🌿"


def extract_product_query(message: str) -> bool:
    keywords = [
        "أبي","ابي","أريد","اريد","بكم","كم سعر","كم ثمن",
        "ما سعر","هل عندكم","عندكم","يوجد","دواء","علاج",
        "توابل","أعشاب","زعتر","كمون","هيل","عسل","زيت",
    ]
    return any(kw in message for kw in keywords)
