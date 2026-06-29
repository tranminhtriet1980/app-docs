"""Trợ lý AI toàn cục: tìm hồ sơ trong dữ liệu sẵn có + hỏi đáp định cư.

Quy tắc: nếu câu hỏi khớp dữ liệu hồ sơ sẵn có → trả lời dựa trên dữ liệu đó (kèm
hồ sơ liên quan). Nếu không có dữ liệu phù hợp → trả lời bằng kiến thức chung qua OpenAI.
"""

import json
import re
import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.entities import Applicant, ProfileField, User
from app.services.llm_client import is_openai_configured
from app.services.llm_usage import UsageContext, chat_completion
from app.services.permissions import is_admin

_STOPWORDS = {
    "hồ", "sơ", "hoso", "của", "là", "gì", "cho", "các", "những", "và", "có", "không",
    "khi", "nào", "ở", "đi", "làm", "cần", "giúp", "tôi", "bạn", "với", "về", "trong",
    "bao", "nhiêu", "ai", "thế", "this", "that", "the", "a", "an", "of", "is", "what",
    "how", "who", "list", "tìm", "kiếm", "xem", "cho", "biết", "hãy", "vui", "lòng",
}


def _tokens(question: str) -> list[str]:
    raw = re.findall(r"[0-9A-Za-zÀ-ỹ]+", question or "")
    return [t for t in raw if len(t) >= 2 and t.lower() not in _STOPWORDS]


ASSISTANT_INTRO = "Tôi là trợ lý AI ImmiPath. Tôi có thể giúp gì cho bạn không?"

# Câu hỏi không tìm thấy thông tin trong dữ liệu ứng dụng (và không trả lời được).
NO_DATA_MSG = "Thông tin bạn hỏi không có trong ứng dụng. AI ImmiPath có thể giúp gì cho bạn không?"

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|halo|alo|helu|h[eế]\s*l[oô]|ch[aà]o|xin\s*ch[aà]o|"
    r"good\s*(morning|afternoon|evening))\b",
    re.IGNORECASE,
)
_IDENTITY_RE = re.compile(
    r"(b[aạ]n\s*l[aà]\s*ai|b[aạ]n\s*t[eê]n\s*(g[iì]|l[aà]\s*g[iì])|ai\s*(đ[aấ]y|v[aậ]y)|"
    r"who\s*are\s*you|gi[oớ]i\s*thi[eệ]u\s*b[aạ]n|b[aạ]n\s*l[aà]m\s*đ[uượ]?c\s*g[iì])",
    re.IGNORECASE,
)


def _is_smalltalk(question: str) -> bool:
    """Câu chào hỏi / hỏi danh tính → trả lời giới thiệu, không cần tìm dữ liệu hay OpenAI."""
    q = (question or "").strip()
    if not q:
        return True
    if _GREETING_RE.search(q) or _IDENTITY_RE.search(q):
        return True
    # Câu quá ngắn, không có token nội dung (vd "hi", "ok", ":)")
    return len(_tokens(q)) == 0 and len(q) <= 12


CAPABILITY_MSG = (
    "Tôi có thể giúp bạn trả lời các câu hỏi liên quan đến hồ sơ định cư, ví dụ:\n"
    "• Tìm hồ sơ theo tên (vd: \"Tìm hồ sơ KHUC THI LE HANG\")\n"
    "• Tra cứu thông tin trong hồ sơ (hộ chiếu, cha/mẹ, tình trạng…)\n"
    "• Giải đáp về giấy tờ & quy trình định cư (DS-260…)\n"
    "Bạn cần tìm gì ạ?"
)


def _ascii(s: str) -> str:
    """Bỏ dấu tiếng Việt + viết thường để so khớp ý định linh hoạt."""
    out = "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return out.replace("đ", "d")


_CAPABILITY_RE = re.compile(
    r"(tim kiem|tim duoc|(giup|lam|ho tro)( duoc)? gi|"
    r"co the (lam|tim|giup|tra cuu|hoi)|chuc nang|huong dan|"
    r"dung (nhu )?the nao|\bhelp\b|lam gi|tim gi)"
)


def _is_capability_question(question: str) -> bool:
    return bool(_CAPABILITY_RE.search(_ascii(question)))


async def _find_relevant_applicants(
    db: AsyncSession, user: User, question: str, limit: int = 5
) -> list[Applicant]:
    toks = _tokens(question)
    if not toks:
        return []
    conds = []
    for t in toks:
        like = f"%{t}%"
        conds.append(
            or_(
                Applicant.display_name.ilike(like),
                Applicant.client_name.ilike(like),
                Applicant.project_name.ilike(like),
                Applicant.notes.ilike(like),
                Applicant.tags.ilike(like),
            )
        )
    q = select(Applicant).where(Applicant.deleted_at.is_(None), or_(*conds))
    if not is_admin(user):
        q = q.where(Applicant.user_id == user.id)
    q = q.order_by(Applicant.updated_at.desc()).limit(limit)
    return list((await db.execute(q)).scalars().all())


async def _context_for_applicants(db: AsyncSession, applicants: list[Applicant]) -> str:
    blocks: list[str] = []
    for a in applicants:
        rows = await db.execute(
            select(ProfileField)
            .where(ProfileField.applicant_id == a.id)
            .order_by(ProfileField.field_key)
        )
        fields = [
            f"  - {r.field_key}: {(r.field_value or '')[:200]}"
            for r in rows.scalars().all()
            if r.field_value
        ][:20]
        blocks.append(
            f"Hồ sơ: {a.display_name} (mã {str(a.id)[:8]}, trạng thái {a.status.value})\n"
            f"  Khách hàng: {a.client_name or '—'} · Dự án: {a.project_name or '—'}\n"
            + ("\n".join(fields) if fields else "  (chưa có dữ liệu trích xuất)")
        )
    return "\n\n".join(blocks)


def _sources(applicants: list[Applicant]) -> list[dict]:
    return [
        {"id": str(a.id), "name": a.display_name, "status": a.status.value}
        for a in applicants
    ]


async def ask_global_assistant(
    db: AsyncSession, *, user: User, question: str
) -> dict:
    # Chào hỏi / hỏi danh tính → trả lời giới thiệu ngay (không cần dữ liệu / OpenAI).
    if _is_smalltalk(question):
        return {"answer": ASSISTANT_INTRO, "sources": [], "source_type": "assistant", "model": None}

    # Hỏi về khả năng ("tìm được gì", "giúp gì"…) → trả lời sẵn, không cần OpenAI.
    if _is_capability_question(question):
        return {"answer": CAPABILITY_MSG, "sources": [], "source_type": "assistant", "model": None}

    applicants = await _find_relevant_applicants(db, user, question)
    has_data = bool(applicants)

    if not is_openai_configured():
        if has_data:
            lines = "\n".join(
                f"• {a.display_name} — {a.status.value}" for a in applicants
            )
            return {
                "answer": f"Tìm thấy {len(applicants)} hồ sơ phù hợp:\n{lines}",
                "sources": _sources(applicants),
                "source_type": "data",
                "model": None,
            }
        return {"answer": NO_DATA_MSG, "sources": [], "source_type": "none", "model": None}

    context = await _context_for_applicants(db, applicants) if has_data else ""
    system = (
        "Bạn là trợ lý ImmiPath về hồ sơ định cư/du học Mỹ. "
        "Nếu phần DỮ LIỆU HỒ SƠ chứa thông tin liên quan câu hỏi, hãy trả lời DỰA TRÊN dữ liệu đó "
        "và nêu rõ tên hồ sơ. Nếu câu hỏi là kiến thức định cư chung (không về hồ sơ cụ thể nào), "
        "trả lời bằng kiến thức chuyên môn của bạn. Trả lời tiếng Việt, ngắn gọn, có cấu trúc. "
        "Không bịa thông tin cá nhân không có trong dữ liệu."
    )
    user_content = (
        (f"DỮ LIỆU HỒ SƠ liên quan:\n{context}\n\n" if has_data else "")
        + f"Câu hỏi: {question}"
    )
    try:
        response = await chat_completion(
            db,
            operation="ai.global_assistant",
            context=UsageContext(user_id=user.id),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        answer = (response.choices[0].message.content or "").strip()
    except Exception:
        # OpenAI lỗi/timeout → không để treo: nếu có dữ liệu thì liệt kê hồ sơ, nếu không thì báo nhẹ.
        if has_data:
            lines = "\n".join(f"• {a.display_name} — {a.status.value}" for a in applicants)
            return {
                "answer": f"Tìm thấy {len(applicants)} hồ sơ phù hợp:\n{lines}",
                "sources": _sources(applicants),
                "source_type": "data",
                "model": None,
            }
        return {"answer": NO_DATA_MSG, "sources": [], "source_type": "none", "model": None}

    if not answer:
        # OpenAI không trả lời được + không có dữ liệu → báo không có trong ứng dụng.
        if not has_data:
            return {"answer": NO_DATA_MSG, "sources": [], "source_type": "none", "model": None}
        answer = "\n".join(f"• {a.display_name} — {a.status.value}" for a in applicants)

    return {
        "answer": answer,
        "sources": _sources(applicants),
        "source_type": "data" if has_data else "openai",
        "model": settings.openai_model,
    }
