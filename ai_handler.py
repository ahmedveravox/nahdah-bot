"""
Gemini AI — direct REST API, multi-model fallback, startup validation
"""
import os
import base64
import logging
import requests
from dotenv import load_dotenv
import database as db

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS   = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro",
]

SYSTEM_PROMPT = """\
أنت موظف خدمة عملاء في عطارة "نهضة أسيا" للأعشاب والتوابل.
قواعد:
- لهجة سعودية خليجية ودية
- رد قصير 2-3 جمل فقط
- رحّب بالعميل بدفء في أول رسالة
- اقترح المنتج المناسب مع سعره
- للطلب وجّهه لـ nhdah.com

المنتجات:
{products}
"""


# ─── Core call ─────────────────────────────────────────────────────────────────

def _gemini_key() -> str:
    """نقرأ المفتاح عند كل استدعاء عشان نضمن إنه محمّل"""
    return os.environ.get("GEMINI_API_KEY", "")


def _post_gemini(model: str, parts: list[dict]) -> str:
    key = _gemini_key()
    if not key:
        logger.error("GEMINI_API_KEY is not set!")
        return ""

    url     = f"{BASE_URL}/{model}:generateContent"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 280},
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in [
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            ]
        ],
    }
    try:
        r = requests.post(
            url, params={"key": key},
            json=payload, timeout=20,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            logger.error(f"[{model}] HTTP {r.status_code}: {r.text[:300]}")
            return ""

        data       = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            finish = data.get("promptFeedback", {}).get("blockReason", "unknown")
            logger.error(f"[{model}] No candidates. blockReason={finish}")
            return ""

        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if not text:
            logger.error(f"[{model}] Empty text in response: {data}")
            return ""

        logger.info(f"[{model}] ✅ {len(text)} chars")
        return text

    except Exception as exc:
        logger.error(f"[{model}] Exception: {exc}")
        return ""


def _call_gemini(parts: list[dict]) -> str:
    """يجرّب الموديلات بالترتيب"""
    for model in MODELS:
        text = _post_gemini(model, parts)
        if text:
            return text
    logger.error("All Gemini models failed.")
    return ""


# ─── Startup validation ────────────────────────────────────────────────────────

def test_gemini() -> tuple[bool, str]:
    """نتأكد إن Gemini شغّال عند تشغيل البوت"""
    text = _call_gemini([{"text": "قل كلمة واحدة فقط: اختبار"}])
    if text:
        return True, text
    return False, "فشل الاتصال بـ Gemini"


# ─── Prompt helpers ────────────────────────────────────────────────────────────

def _products_ctx(products: list[dict]) -> str:
    if not products:
        return "لا توجد منتجات."
    lines = []
    for p in products[:40]:           # 40 منتج كافي — أقصر prompt
        price = f" ({p['price']} ريال)" if p.get("price") else ""
        name  = p.get("name_ar") or p.get("name") or ""
        lines.append(f"• {name}{price}")
    return "\n".join(lines)


def _build_prompt(user_message: str, products: list[dict], history: list[dict]) -> str:
    system = SYSTEM_PROMPT.format(products=_products_ctx(products))

    # آخر 4 رسائل فقط عشان ما يطول الـ prompt
    hist_lines = []
    for m in history[-4:]:
        role = "عميل" if m["role"] == "user" else "أنت"
        hist_lines.append(f"{role}: {m['message']}")
    hist = ("\n".join(hist_lines) + "\n") if hist_lines else ""

    return f"{system}\n{hist}عميل: {user_message}\nردك:"


# ─── Public API ────────────────────────────────────────────────────────────────

async def generate_reply(user_id: int, user_message: str, products: list[dict]) -> str:
    history = db.get_conversation_history(user_id, limit=6)
    prompt  = _build_prompt(user_message, products, history)
    text    = _call_gemini([{"text": prompt}])
    return text if text else _fallback(user_message, products)


async def generate_reply_image(
    user_id: int, image_bytes: bytes, caption: str, products: list[dict]
) -> str:
    system = SYSTEM_PROMPT.format(products=_products_ctx(products))
    prompt = (
        f"{system}\n"
        f"العميل أرسل صورة{' وكتب: ' + caption if caption else '.'} "
        f"حدّد المنتج أو اقترح الأنسب. ردك:"
    )
    img_b64 = base64.b64encode(image_bytes).decode()
    text    = _call_gemini([
        {"text": prompt},
        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
    ])
    return text if text else "وصلت الصورة 📸 — اكتب اسم المنتج وأساعدك! 🌿"


async def generate_reply_voice(
    user_id: int, audio_bytes: bytes, products: list[dict]
) -> str:
    system    = SYSTEM_PROMPT.format(products=_products_ctx(products))
    prompt    = f"{system}\nالعميل أرسل رسالة صوتية. اسمع وارد باللهجة السعودية. ردك:"
    audio_b64 = base64.b64encode(audio_bytes).decode()
    text      = _call_gemini([
        {"text": prompt},
        {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}},
    ])
    return text if text else "سمعت رسالتك 🎙️ — اكتب طلبك بالنص وأخدمك! 🌿"


# ─── Fallback ──────────────────────────────────────────────────────────────────

def _fallback(message: str, products: list[dict]) -> str:
    for p in products:
        name = p.get("name_ar") or p.get("name") or ""
        if name and name in message:
            price = f" بسعر {p['price']} ريال" if p.get("price") else ""
            return f"عندنا {name}{price} 🌿 تقدر تطلب من nhdah.com"
    return "هلا بك! 👋 كيف أقدر أخدمك؟ اكتب اسم المنتج اللي تبيه 🌿"


def extract_product_query(message: str) -> bool:
    return any(kw in message for kw in [
        "أبي","ابي","أريد","اريد","بكم","كم سعر","كم ثمن",
        "ما سعر","هل عندكم","عندكم","يوجد","دواء","علاج",
        "توابل","أعشاب","زعتر","كمون","هيل","عسل","زيت",
    ])
