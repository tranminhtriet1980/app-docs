from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import admin, applicants, auth, auth_security, chat, documents, export, notifications, profile, reports, search, usage
from app.config import settings
from app.database import init_db
from app.services.export import ensure_default_templates
from app.database import async_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session() as db:
        await ensure_default_templates(db)
        await db.commit()
    yield


app = FastAPI(
    title="Immigration & Study Abroad AI Form Filler",
    description="Upload documents → OCR/extract → merge profile → review → export Word forms",
    version="1.0.0",
    lifespan=lifespan,
)

# Cho phép mọi IP LAN (10.x, 172.16-31.x, 192.168.x) + localhost trên bất kỳ port nào.
_PRIVATE_NETWORK_ORIGIN_RE = (
    r"https?://"
    r"(localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3})"
    r"(:\d+)?"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=_PRIVATE_NETWORK_ORIGIN_RE,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = "/api/v1"

app.include_router(auth.router, prefix=prefix)
app.include_router(auth_security.router, prefix=prefix)
app.include_router(notifications.router, prefix=prefix)
app.include_router(usage.router, prefix=prefix)
app.include_router(search.router, prefix=prefix)
app.include_router(reports.router, prefix=prefix)
app.include_router(chat.router, prefix=prefix)
app.include_router(admin.router, prefix=prefix)
app.include_router(applicants.router, prefix=prefix)
app.include_router(documents.router, prefix=prefix)
app.include_router(profile.router, prefix=prefix)
app.include_router(export.router, prefix=prefix)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


def _health_payload() -> dict:
    pdf_renderer = "none"
    try:
        import fitz  # noqa: F401

        pdf_renderer = "pymupdf"
    except ImportError:
        try:
            import pdf2image  # noqa: F401

            pdf_renderer = "pdf2image"
        except ImportError:
            pass
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "openai_model": settings.openai_model if settings.openai_api_key else None,
        "pdf_renderer": pdf_renderer,
        "monthly_token_budget": settings.monthly_token_budget or None,
    }


@app.get("/health")
@app.head("/health")
async def health():
    return _health_payload()
