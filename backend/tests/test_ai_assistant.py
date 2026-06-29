"""Trợ lý toàn cục: tách token + tìm hồ sơ liên quan (có phân quyền)."""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import Applicant, User, UserRole
from app.services.ai_assistant import _find_relevant_applicants, _tokens


def test_smalltalk_detection():
    from app.services.ai_assistant import _is_smalltalk

    for q in ["hello", "hi", "Chào bạn", "xin chào", "bạn là ai?", "bạn tên gì", "who are you"]:
        assert _is_smalltalk(q), q
    for q in ["Tìm hồ sơ KHUC THI LE HANG", "DS-260 cần giấy tờ gì?"]:
        assert not _is_smalltalk(q), q


def test_capability_question_detection():
    from app.services.ai_assistant import _is_capability_question

    for q in [
        "Tôi có thể tìm kiếm những gì",
        "bạn giúp được gì?",
        "Bạn làm được gì",
        "có thể tra cứu gì",
        "hướng dẫn sử dụng",
    ]:
        assert _is_capability_question(q), q
    assert not _is_capability_question("Tìm hồ sơ KHUC THI LE HANG")


def test_tokens_drops_stopwords_and_short():
    toks = [t.lower() for t in _tokens("Tìm hồ sơ KHUC THI LE HANG giúp tôi")]
    assert "khuc" in toks and "hang" in toks
    assert "hồ" not in toks and "sơ" not in toks and "tôi" not in toks


async def _setup(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ai.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_no_data_message_when_openai_unavailable(tmp_path, monkeypatch):
    import app.services.ai_assistant as mod

    monkeypatch.setattr(mod, "is_openai_configured", lambda: False)

    async def scenario():
        engine, Session = await _setup(tmp_path)
        uid = uuid.uuid4()
        async with Session() as db:
            user = User(id=uid, email="t@t.com", hashed_password="x", role=UserRole.user)
            db.add(user)
            await db.commit()

            # Câu hỏi chung, không có dữ liệu, OpenAI tắt → báo "không có trong ứng dụng"
            res = await mod.ask_global_assistant(db, user=user, question="DS-260 cần giấy tờ gì")
            assert res["answer"] == mod.NO_DATA_MSG
            assert res["source_type"] == "none"

            # Chào hỏi vẫn trả lời giới thiệu (không phụ thuộc OpenAI)
            hi = await mod.ask_global_assistant(db, user=user, question="hello")
            assert hi["answer"] == mod.ASSISTANT_INTRO
        await engine.dispose()

    asyncio.run(scenario())


def test_find_relevant_applicants_scoped(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path)
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        async with Session() as db:
            user1 = User(id=u1, email="a@t.com", hashed_password="x", role=UserRole.user)
            db.add_all([
                user1,
                User(id=u2, email="b@t.com", hashed_password="x", role=UserRole.user),
                Applicant(id=uuid.uuid4(), user_id=u1, display_name="TRAN VAN A"),
                Applicant(id=uuid.uuid4(), user_id=u2, display_name="TRAN VAN B"),
            ])
            await db.commit()

            # u1 hỏi "tran" → chỉ thấy hồ sơ của mình (TRAN VAN A), không thấy của u2
            found = await _find_relevant_applicants(db, user1, "tìm hồ sơ tran van a")
            names = [a.display_name for a in found]
            assert "TRAN VAN A" in names
            assert "TRAN VAN B" not in names

            # admin thấy tất cả
            admin = User(id=uuid.uuid4(), email="ad@t.com", hashed_password="x", role=UserRole.admin)
            found_admin = await _find_relevant_applicants(db, admin, "tran")
            assert {"TRAN VAN A", "TRAN VAN B"} <= {a.display_name for a in found_admin}

            # Câu hỏi chung, không khớp tên hồ sơ nào
            assert await _find_relevant_applicants(db, user1, "DS-260 cần giấy tờ gì") == []
        await engine.dispose()

    asyncio.run(scenario())
