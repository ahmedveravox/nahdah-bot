"""
Claude AI handler — Anthropic API (claude-haiku-4-5-20251001)
"""
import os
import base64
import logging
import requests
from dotenv import load_dotenv
import database as db

load_dotenv()
logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL         = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
أنت موظف خدمة عملاء في عطارة "نهضة أسيا" للأعشاب والتوابل والمنتجات الطبيعية.

قواعد صارمة:
- تحكي باللهجة السعودية الخليجية الودية دائماً
- ردودك قصيرة 2-3 جمل فقط
- رحّب بالعميل بدفء في أول رسالة
- اقترح المنتج المناسب من القائمة مع سعره
- إذا ما عندنا المنتج اقترح الأقرب
- للطلب وجّهه لـ nhdah.com
- لا تتكلم في مواضيع غير العطارة والمنتجات

المنتجات المتاحة:
{products}
"""


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _headers() -> dict:
    return {
        "x-api-key":         _api_key(),
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }


def _products_ctx(products: list[dict]) -> str:
    if not products:
        return "لا توجد منتجات محمّلة حالياً."
    lines = []
    for p in products[:50]:
        price = f" ({p['price']} ريال)" if p.get("price") else ""
        name  = p.get("name_ar") or p.get("name") or ""
        lines.append(f"• {name}{price}")
    return "\n".join(lines)


def _build_messages(user_message: str, history: list[dict]) -> list[dict]:
    messages = []
    for m in history[-6:]:
        role = "user" if m["role"] == "user" else "assistant"
        messages.append({"role": role, "content": m["message"]})
    # تأكد إن أول رسالة دايماً user
    if messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    messages.append({"role": "user", "content": user_message})
    return messages


def _call_claude(system: str, messages: list[dict]) -> str:
    key = _api_key()
    if not key:
        logger.error("ANTHROPIC_API_KEY is not set!")
        return ""
    try:
        payload = {
            "model":      MODEL,
            "max_tokens": 300,
            "system":     system,
            "messages":   messages,
        }
        r = requests.post(ANTHROPIC_URL, headers=_headers(), json=payload, timeout=20)
        if r.status_code != 200:
            logger.error(f"Claude HTTP {r.status_code}: {r.text[:400]}")
            return ""
        data    = r.json()
        content = data.get("content", [])
        text    = content[0].get("text", "").strip() if content else ""
        logger.info(f"Claude ✅ {len(text)} chars")
        return text
    except Exception as exc:
        logger.error(f"Claude call failed: {exc}")
        return ""


# ─── Startup test ──────────────────────────────────────────────────────────────

def test_claude() -> tuple[bool, str]:
    text = _call_claude(
        system="رد بكلمة واحدة فقط.",
        messages=[{"role": "user", "content": "اختبار"}],
    )
    return (True, text) if text else (False, "فشل الاتصال بـ Claude API")


# ─── Public API ────────────────────────────────────────────────────────────────

async def generate_reply(user_id: int, user_message: str, products: list[dict]) -> str:
    history  = db.get_conversation_history(user_id, limit=6)
    system   = SYSTEM_PROMPT.format(products=_products_ctx(products))
    messages = _build_messages(user_message, history)
    text     = _call_claude(system, messages)
    return text if text else _fallback(user_message, products)


async def generate_reply_image(
    user_id: int, image_bytes: bytes, caption: str, products: list[dict]
) -> str:
    system  = SYSTEM_PROMPT.format(products=_products_ctx(products))
    img_b64 = base64.b64encode(image_bytes).decode()
    content = [
        {
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": "image/jpeg",
                "data":       img_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"العميل أرسل صورة{' وكتب: ' + caption if caption else '.'} "
                "حدّد المنتج في الصورة أو اقترح الأنسب من قائمتنا. ردك:"
            ),
        },
    ]
    text = _call_claude(system, [{"role": "user", "content": content}])
    return text if text else "وصلت الصورة 📸 — اكتب اسم المنتج وأساعدك! 🌿"


async def generate_reply_voice(
    user_id: int, audio_bytes: bytes, products: list[dict]
) -> str:
    # Claude ما يدعم الصوت مباشرة — نطلب من العميل يكتب
    return "وصلت رسالتك الصوتية 🎙️ — للأسف ما أقدر أسمع الصوت، اكتب طلبك وأخدمك بأسرع وقت! 🌿"


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
