"""
Knowledge Base Management & Evaluation Gate API Router
Complies with Specification Section 5.3, 16.6, and 17.

Provides:
- Policy document upload & clause preview extraction (PDF, MD, TXT).
- Confirmed policy values submission and draft creation.
- Catalog ingestion triggering with 1-active-job constraint and Deletion Guard.
- Background ingestion job polling.
- Pre-promotion automated evaluation gate runner.
- Atomic version promotion with Manager/Admin role gate and step-up override.
- One-click version rollback.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from db.models import KnowledgeVersion, IngestionJob
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    StaffSessionContext, get_current_staff, require_roles
)
from ingestion.manifest_engine import (
    KnowledgeManifestEngine, extract_policy_text, parse_policy_clauses
)

router = APIRouter(prefix="/api/admin/v1/knowledge", tags=["Knowledge & Policies"])
manifest_engine = KnowledgeManifestEngine()


class ConfirmedPolicyForm(BaseModel):
    return_window_days: int = Field(default=30, ge=1, le=365)
    excluded_categories: List[str] = Field(default_factory=lambda: ["digital", "gift cards", "perishables"])
    auto_refund_limit_inr: int = Field(default=2000, ge=0, le=50000)


class CreatePolicyDraftRequest(BaseModel):
    filename: str
    clauses: List[Dict[str, Any]]
    confirmed_policy: ConfirmedPolicyForm


class CatalogSyncRequest(BaseModel):
    products: Optional[List[Dict[str, Any]]] = None


class PromoteVersionRequest(BaseModel):
    override: bool = False
    override_reason: Optional[str] = None


class RollbackRequest(BaseModel):
    version_type: str = Field(..., description="'policy' or 'catalog'")


@router.post("/policy/upload")
async def upload_policy_document(
    file: UploadFile = File(...),
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """
    Accepts PDF, Markdown, or Text policy file.
    Extracts text, verifies quality (rejects scanned PDFs / >30% glyph corruption),
    and returns a structured clause preview.
    """
    try:
        content = await file.read()
        raw_text = extract_policy_text(content, file.filename)
        clauses = parse_policy_clauses(raw_text)
        return {
            "filename": file.filename,
            "total_clauses": len(clauses),
            "clauses": clauses,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process policy document: {str(e)}"
        )


@router.post("/policy/draft")
async def create_policy_draft(
    payload: CreatePolicyDraftRequest,
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """
    Creates a new draft policy version with confirmed parameters and content-addressed chunks.
    """
    if not payload.clauses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one policy clause is required to create a policy draft."
        )

    async with get_async_session(staff.tenant_id) as session:
        version = await manifest_engine.create_policy_draft(
            tenant_id=staff.tenant_id,
            staff_id=staff.staff_id,
            filename=payload.filename,
            clauses=payload.clauses,
            confirmed_values=payload.confirmed_policy.model_dump(),
            session=session
        )
        return {
            "version_id": version.version_id,
            "tenant_id": version.tenant_id,
            "type": version.type,
            "status": version.status,
            "manifest": version.manifest,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }


@router.post("/catalog/sync")
async def sync_catalog(
    payload: Optional[CatalogSyncRequest] = None,
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """
    Triggers catalog ingestion. Enforces 1 active job per tenant and Deletion Guard.
    """
    products_override = payload.products if payload else None
    async with get_async_session(staff.tenant_id) as session:
        try:
            job = await manifest_engine.run_catalog_ingestion_job(
                tenant_id=staff.tenant_id,
                staff_id=staff.staff_id,
                session=session,
                products_override=products_override
            )
            return {
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "status": job.status,
                "progress_pct": job.progress_pct,
                "error_message": job.error_message,
                "stats": job.stats,
            }
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/jobs/{job_id}")
async def get_ingestion_job(
    job_id: str,
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """Retrieves status and progress of an ingestion job."""
    async with get_async_session(staff.tenant_id) as session:
        job = await session.get(IngestionJob, job_id)
        if not job or job.tenant_id != staff.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

        return {
            "job_id": job.job_id,
            "tenant_id": job.tenant_id,
            "source_type": job.source_type,
            "status": job.status,
            "progress_pct": job.progress_pct,
            "error_message": job.error_message,
            "stats": job.stats,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }


@router.get("/versions")
async def list_versions(
    type: Optional[str] = Query(None, description="'policy' or 'catalog'"),
    status_filter: Optional[str] = Query(None, alias="status", description="'draft', 'active', 'archived'"),
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """Lists knowledge versions for current tenant."""
    async with get_async_session(staff.tenant_id) as session:
        stmt = select(KnowledgeVersion).where(KnowledgeVersion.tenant_id == staff.tenant_id)
        if type:
            stmt = stmt.where(KnowledgeVersion.type == type)
        if status_filter:
            stmt = stmt.where(KnowledgeVersion.status == status_filter)
        stmt = stmt.order_by(KnowledgeVersion.created_at.desc())

        versions = (await session.execute(stmt)).scalars().all()
        return [
            {
                "version_id": v.version_id,
                "type": v.type,
                "status": v.status,
                "chunk_count": v.manifest.get("chunk_count") if v.manifest else 0,
                "eval_result": v.manifest.get("eval_result") if v.manifest else None,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "promoted_at": v.promoted_at.isoformat() if v.promoted_at else None,
            }
            for v in versions
        ]


@router.get("/versions/{version_id}")
async def get_version_details(
    version_id: str,
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """Fetches complete manifest details of a knowledge version."""
    async with get_async_session(staff.tenant_id) as session:
        version = await session.get(KnowledgeVersion, version_id)
        if not version or version.tenant_id != staff.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version '{version_id}' not found.")

        return {
            "version_id": version.version_id,
            "tenant_id": version.tenant_id,
            "type": version.type,
            "status": version.status,
            "manifest": version.manifest,
            "created_by": version.created_by,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "promoted_at": version.promoted_at.isoformat() if version.promoted_at else None,
        }


@router.post("/versions/{version_id}/eval")
async def run_version_eval(
    version_id: str,
    staff: StaffSessionContext = Depends(get_current_staff),
):
    """
    Executes automated pre-promotion evaluation gate against a draft version.
    Asserts 100% on deterministic rules and >= 90% on fuzzy scenarios.
    """
    async with get_async_session(staff.tenant_id) as session:
        try:
            eval_result = await manifest_engine.run_version_eval(
                tenant_id=staff.tenant_id,
                version_id=version_id,
                session=session
            )
            return {
                "version_id": version_id,
                "eval_result": eval_result,
            }
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/versions/{version_id}/promote")
async def promote_version(
    version_id: str,
    payload: PromoteVersionRequest,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """
    Promotes draft version to active status.
    Requires Manager or Admin role.
    If eval failed or not run, requires Manager step-up and written justification.
    """
    async with get_async_session(staff.tenant_id) as session:
        try:
            version = await manifest_engine.promote_version(
                tenant_id=staff.tenant_id,
                version_id=version_id,
                staff_id=staff.staff_id,
                staff_role=staff.role,
                is_stepped_up=staff.is_stepped_up,
                session=session,
                override=payload.override,
                override_reason=payload.override_reason,
            )
            return {
                "version_id": version.version_id,
                "status": version.status,
                "promoted_at": version.promoted_at.isoformat() if version.promoted_at else None,
                "message": f"Version '{version_id}' successfully promoted to active.",
            }
        except PermissionError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/rollback")
async def rollback_version(
    payload: RollbackRequest,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """
    Rolls back to the most recently archived version of the given type.
    Requires Manager or Admin role.
    """
    async with get_async_session(staff.tenant_id) as session:
        try:
            target = await manifest_engine.rollback_version(
                tenant_id=staff.tenant_id,
                version_type=payload.version_type,
                staff_id=staff.staff_id,
                staff_role=staff.role,
                session=session,
            )
            return {
                "version_id": target.version_id,
                "type": target.type,
                "status": target.status,
                "promoted_at": target.promoted_at.isoformat() if target.promoted_at else None,
                "message": f"Successfully rolled back to version '{target.version_id}'.",
            }
        except PermissionError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
