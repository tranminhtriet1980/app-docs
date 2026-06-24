"""Log OpenAI API token usage per request."""

import uuid
from dataclasses import dataclass

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import ApiUsageLog
from app.services.llm_client import get_openai_client


@dataclass
class UsageContext:
    user_id: uuid.UUID | None = None
    applicant_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    filename: str | None = None
    doc_type: str | None = None


def _usage_from_response(response: ChatCompletion | None) -> tuple[int, int, int]:
    if not response or not response.usage:
        return 0, 0, 0
    u = response.usage
    prompt = int(u.prompt_tokens or 0)
    completion = int(u.completion_tokens or 0)
    total = int(u.total_tokens or (prompt + completion))
    return prompt, completion, total


async def log_llm_usage(
    db: AsyncSession,
    response: ChatCompletion | None,
    *,
    operation: str,
    context: UsageContext | None = None,
    model: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> ApiUsageLog:
    ctx = context or UsageContext()
    prompt, completion, total = _usage_from_response(response)
    entry = ApiUsageLog(
        user_id=ctx.user_id,
        applicant_id=ctx.applicant_id,
        document_id=ctx.document_id,
        operation=operation,
        model=model or settings.openai_model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        filename=ctx.filename,
        doc_type=ctx.doc_type,
        success=success,
        error_message=error_message,
    )
    db.add(entry)
    await db.flush()
    return entry


async def chat_completion(
    db: AsyncSession,
    *,
    operation: str,
    context: UsageContext | None,
    messages: list,
    client: AsyncOpenAI | None = None,
    **kwargs,
) -> ChatCompletion:
    """Call OpenAI chat.completions and persist token usage."""
    client = client or get_openai_client()
    call_kwargs = dict(kwargs)
    model = call_kwargs.pop("model", None) or settings.openai_model
    try:
        response = await client.chat.completions.create(model=model, messages=messages, **call_kwargs)
        await log_llm_usage(db, response, operation=operation, context=context, model=model, success=True)
        return response
    except Exception as exc:
        await log_llm_usage(
            db,
            None,
            operation=operation,
            context=context,
            model=model,
            success=False,
            error_message=str(exc)[:500],
        )
        raise


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """Rough cost from config (per 1M tokens)."""
    input_cost = settings.openai_input_cost_per_1m * prompt_tokens / 1_000_000
    output_cost = settings.openai_output_cost_per_1m * completion_tokens / 1_000_000
    return round(input_cost + output_cost, 6)
