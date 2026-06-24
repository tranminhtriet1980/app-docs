import re
import uuid
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_applicant, require_admin
from app.database import get_db
from app.models.entities import Applicant, ApplicantStatus, Conflict, ConflictStatus, Document, Export, FormTemplate, ProfileField, User
from app.schemas import (
    Ds260BatchExportOut,
    Ds260ExportRequest,
    Ds260MemberExportOut,
    ExportOut,
    ExportRequest,
    FormTemplateOut,
    MessageOut,
)
from app.services.audit import log_audit
from app.services.auth import get_current_user
from app.config import settings
from app.services.export import (
    create_export,
    delete_form_template as remove_form_template,
    ensure_default_templates,
    register_template_file,
)
from app.services.export_ds260 import (
    DS260_DEFAULT_TEMPLATE_CODE,
    create_ds260_export,
)
from app.services.family_case import load_case_members
from app.services.permissions import can_access_applicant
from app.services.zip_export import build_applicant_zip

router = APIRouter(tags=["export"])


@router.get("/form-templates", response_model=list[FormTemplateOut])
async def list_templates(db: Annotated[AsyncSession, Depends(get_db)]):
    await ensure_default_templates(db)
    await db.commit()
    result = await db.execute(select(FormTemplate).where(FormTemplate.is_active.is_(True)).order_by(FormTemplate.name))
    return result.scalars().all()


@router.post("/form-templates/upload", response_model=FormTemplateOut, status_code=status.HTTP_201_CREATED)
async def upload_form_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(require_admin)],
    file: UploadFile = File(...),
    code: str = Form(..., description="Mã form, vd: ds160_custom"),
    name: str = Form("", description="Tên hiển thị"),
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file .docx")

    safe_code = re.sub(r"[^a-zA-Z0-9_-]", "_", code).lower()
    safe_code = re.sub(r"_+", "_", safe_code).strip("_")
    if "ds260" not in safe_code and re.search(r"ds[\s\-]?260", f"{code} {name}", re.I):
        safe_code = f"ds260_{safe_code}" if safe_code else "ds260_custom"
    dest = settings.templates_path / f"{safe_code}.docx"
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File quá lớn (tối đa 10MB)")

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    display_name = name.strip() or safe_code.replace("_", " ").title()
    template = await register_template_file(db, safe_code, display_name, dest)
    await log_audit(db, user=_user, action="template.upload", entity_type="template", entity_id=template.id, payload={"code": safe_code})
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/form-templates/{template_id}", response_model=MessageOut)
async def delete_form_template_route(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_admin)],
):
    """Xóa mẫu form đã upload (file .docx + bản ghi DB)."""
    tpl = await remove_form_template(db, template_id)
    await log_audit(
        db,
        user=user,
        action="template.delete",
        entity_type="template",
        entity_id=tpl.id,
        payload={"code": tpl.code},
    )
    await db.commit()
    return MessageOut(message=f"Đã xóa mẫu form '{tpl.name}' ({tpl.code})")


@router.post("/applicants/{applicant_id}/export", response_model=ExportOut, status_code=status.HTTP_201_CREATED)
async def export_form(
    body: ExportRequest,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    open_count = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(Conflict.applicant_id == applicant.id, Conflict.status == ConflictStatus.open)
    )
    if open_count and open_count > 0:
        raise HTTPException(status_code=400, detail="Resolve open conflicts before export")

    result = await db.execute(select(ProfileField).where(ProfileField.applicant_id == applicant.id))
    fields = list(result.scalars().all())

    try:
        export = await create_export(db, applicant, fields, body.template_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await log_audit(db, user=user, action="export.create", entity_type="export", entity_id=export.id, payload={"template": body.template_code})
    await db.commit()
    await db.refresh(export)

    return ExportOut(
        id=export.id,
        file_path=export.file_path,
        download_url=f"/api/v1/exports/{export.id}/download",
        created_at=export.created_at,
    )


@router.post("/applicants/{applicant_id}/export-ds260", response_model=ExportOut, status_code=status.HTTP_201_CREATED)
async def export_ds260_form(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    body: Ds260ExportRequest | None = None,
):
    """Xuất DS260 từ document mapping — validate trước khi export."""
    from app.services.doc_record_sync import list_doc_records

    records = await list_doc_records(db, applicant.id)
    doc_ids = [r.source_document_id for r in records if r.source_document_id]
    names: dict[str, str] = {}
    if doc_ids:
        result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        names = {str(doc.id): doc.original_filename or "" for doc in result.scalars().all()}

    try:
        export, validation = await create_ds260_export(
            db,
            applicant,
            filename_map=names,
            skip_validation=body.skip_validation if body else False,
            template_code=body.template_code if body else DS260_DEFAULT_TEMPLATE_CODE,
            member_id=body.member_id if body else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await log_audit(
        db,
        user=user,
        action="export.ds260",
        entity_type="export",
        entity_id=export.id,
        payload={
            "valid": validation.get("valid"),
            "error_count": validation.get("error_count"),
            "warning_count": validation.get("warning_count"),
        },
    )
    await db.commit()
    await db.refresh(export)

    return ExportOut(
        id=export.id,
        file_path=export.file_path,
        download_url=f"/api/v1/exports/{export.id}/download",
        created_at=export.created_at,
    )


@router.post(
    "/applicants/{applicant_id}/export-ds260-batch",
    response_model=Ds260BatchExportOut,
    status_code=status.HTTP_201_CREATED,
)
async def export_ds260_batch(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    body: Ds260ExportRequest | None = None,
):
    """Xuất DS-260 cho tất cả thành viên trong bộ hồ sơ gia đình."""
    from app.services.doc_record_sync import list_doc_records

    members = await load_case_members(db, applicant.id)
    if not members:
        raise HTTPException(status_code=400, detail="Hồ sơ không có thành viên gia đình. Tạo bộ hồ sơ gia đình trước.")

    records = await list_doc_records(db, applicant.id)
    doc_ids = [r.source_document_id for r in records if r.source_document_id]
    names: dict[str, str] = {}
    if doc_ids:
        result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        names = {str(doc.id): doc.original_filename or "" for doc in result.scalars().all()}

    exports_out: list[Ds260MemberExportOut] = []
    failed: list[dict[str, str]] = []
    skip_val = body.skip_validation if body else False
    tpl = body.template_code if body else DS260_DEFAULT_TEMPLATE_CODE

    for member in members:
        try:
            export, _validation = await create_ds260_export(
                db,
                applicant,
                filename_map=names,
                skip_validation=skip_val,
                template_code=tpl,
                member_id=member.id,
            )
            exports_out.append(
                Ds260MemberExportOut(
                    id=export.id,
                    file_path=export.file_path,
                    download_url=f"/api/v1/exports/{export.id}/download",
                    created_at=export.created_at,
                    member_id=member.id,
                    member_name=member.display_name,
                    member_role=member.role,
                )
            )
        except ValueError as e:
            failed.append({"member": member.display_name, "error": str(e)})

    await log_audit(
        db,
        user=user,
        action="export.ds260.batch",
        entity_type="applicant",
        entity_id=applicant.id,
        payload={"export_count": len(exports_out), "failed": len(failed)},
    )
    await db.commit()
    return Ds260BatchExportOut(exports=exports_out, failed=failed)


@router.get("/applicants/{applicant_id}/export-zip")
async def download_applicant_zip(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    data, filename = await build_applicant_zip(db, applicant.id)
    if not data:
        raise HTTPException(status_code=404, detail="No documents to export")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Export).where(Export.id == export_id))
    export = result.scalar_one_or_none()
    if export:
        applicant = await db.get(Applicant, export.applicant_id)
        if not applicant or not can_access_applicant(user, applicant):
            export = None
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    path = Path(export.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file missing")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
