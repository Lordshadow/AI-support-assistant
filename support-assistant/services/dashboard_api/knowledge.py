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

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import KnowledgeVersion, IngestionJob, IngestionRun, IngestionItem, AuditEvent
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    StaffSessionContext, get_current_staff, require_roles
)
from ingestion.manifest_engine import (
    KnowledgeManifestEngine, JobCancelledException, extract_policy_text, parse_policy_clauses
)

router = APIRouter(prefix="/api/admin/v1/knowledge", tags=["Knowledge & Policies"])
manifest_engine = KnowledgeManifestEngine()
catalog_job_progress: Dict[str, Dict[str, Any]] = {}
logger = __import__("logging").getLogger(__name__)


async def _run_catalog_ingestion(tenant_id: str, staff_id: str, job_id: str, staff_role: str = "manager",
                                 retry_product_ids: Optional[List[str]] = None,
                                 allow_large_catalog_decrease: bool = False):
    """Run import outside the request transaction and persist progress for polling."""
    def update_progress(progress: Dict[str, Any]):
        catalog_job_progress[job_id] = progress

    try:
        async with get_async_session(tenant_id) as session:
            await manifest_engine.run_catalog_ingestion_job(
                tenant_id=tenant_id,
                staff_id=staff_id,
                session=session,
                ingestion_job_id=job_id,
                progress_callback=update_progress,
                staff_role=staff_role,
                retry_product_ids=retry_product_ids,
                allow_large_catalog_decrease=allow_large_catalog_decrease,
            )
    except Exception as exc:
        is_cancelled = (
            manifest_engine.is_job_cancelled(job_id)
            or isinstance(exc, (asyncio.CancelledError, JobCancelledException))
            or "cancelled" in str(exc).lower()
        )
        if is_cancelled:
            logger.info("Catalog ingestion job %s was cancelled by staff.", job_id)
            catalog_job_progress[job_id] = {
                "job_id": job_id, "status": "cancelled", "progress_pct": 100,
                "error_message": "Catalog import cancelled by staff.",
                "stats": {"cancelled": True},
            }
            try:
                async with get_async_session(tenant_id) as err_session:
                    job_row = await err_session.get(IngestionJob, job_id)
                    if job_row:
                        job_row.status = "cancelled"
                        job_row.error_message = "Catalog import cancelled by staff."
                        job_row.progress_pct = 100
                    run_row = await err_session.scalar(select(IngestionRun).where(IngestionRun.job_id == job_id))
                    if run_row:
                        run_row.status = "cancelled"
                        run_row.finished_at = datetime.now(timezone.utc)
                    await err_session.commit()
            except Exception:
                pass
            return

        logger.exception("Catalog ingestion job %s failed: %s", job_id, exc)
        catalog_job_progress[job_id] = {
            "job_id": job_id, "status": "failed", "progress_pct": 100,
            "error_message": f"Catalog import failed: {str(exc)[:200]}",
            "stats": {"failures": [str(exc)[:200]]},
        }
        try:
            async with get_async_session(tenant_id) as err_session:
                job_row = await err_session.get(IngestionJob, job_id)
                if job_row:
                    job_row.status = "failed"
                    job_row.error_message = str(exc)[:300]
                    job_row.progress_pct = 100
                run_row = await err_session.scalar(select(IngestionRun).where(IngestionRun.job_id == job_id))
                if run_row:
                    run_row.status = "failed"
                    run_row.finished_at = datetime.now(timezone.utc)
                    run_row.errors = [{"error": str(exc)[:300]}]
                await err_session.commit()
        except Exception:
            pass


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
    allow_large_catalog_decrease: bool = Field(
        default=False,
        description="Explicit manager/admin approval to replace an active catalog with fewer than 80% of its prior products.",
    )


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
    background_tasks: BackgroundTasks,
    payload: Optional[CatalogSyncRequest] = None,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """
    Triggers catalog ingestion. Enforces 1 active job per tenant and Deletion Guard.
    """
    products_override = payload.products if payload else None
    allow_large_catalog_decrease = bool(payload and payload.allow_large_catalog_decrease)
    if products_override is None:
        job = None
        try:
            async with get_async_session(staff.tenant_id) as session:
                active = (await session.execute(select(IngestionJob).where(
                    IngestionJob.tenant_id == staff.tenant_id,
                    IngestionJob.source_type == "catalog",
                    IngestionJob.status.in_(["queued", "running"]),
                ))).scalars().first()
                if active:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A catalog import is already running.",
                        headers={"X-Active-Job-Id": active.job_id},
                    )
                job = IngestionJob(
                    job_id=f"job_cat_{uuid.uuid4().hex[:12]}", tenant_id=staff.tenant_id,
                    source_type="catalog", status="queued", progress_pct=0,
                    stats={"products_seen": 0, "products_processed": 0, "chunks_indexed": 0},
                )
                session.add(job)
                session.add(IngestionRun(run_id=f"run_{job.job_id}", job_id=job.job_id,
                    tenant_id=staff.tenant_id, status="queued", stats={}, errors=[], logs=[]))
        except IntegrityError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A catalog import is already running.")
        background_tasks.add_task(
            _run_catalog_ingestion, staff.tenant_id, staff.staff_id, job.job_id,
            staff.role, None, allow_large_catalog_decrease,
        )
        return {"job_id": job.job_id, "run_id": f"run_{job.job_id}", "tenant_id": job.tenant_id,
                "status": job.status, "progress_pct": job.progress_pct, "error_message": None, "stats": job.stats}

    async with get_async_session(staff.tenant_id) as session:
        try:
            job = await manifest_engine.run_catalog_ingestion_job(
                tenant_id=staff.tenant_id,
                staff_id=staff.staff_id,
                session=session,
                products_override=products_override,
                staff_role=staff.role,
                allow_large_catalog_decrease=allow_large_catalog_decrease,
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


@router.get("/catalog/preview")
async def preview_catalog(
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    """Read a small, server-side sample and source count before a full catalog import."""
    from ingestion.shop_catalog import get_catalog_connector

    try:
        page = await get_catalog_connector().fetch_page(page=1, limit=5)
        pagination = page.get("pagination") or {}
        return {
            "source": "ApexStore",
            "total_products": int(pagination.get("total", len(page["products"]))),
            "sample": page["products"][:5],
            "page_size": int(pagination.get("limit", 5)),
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Could not preview the ApexStore catalog: {str(exc)[:300]}")


@router.get("/catalog/health")
async def catalog_ingestion_health(
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """Probe Postgres/pgvector, the configured embedder, and the read-only shop API."""
    results: Dict[str, Any] = {}
    try:
        async with get_async_session(staff.tenant_id) as session:
            await session.execute(select(IngestionJob.job_id).limit(1))
            results["vector_db"] = {"status": "healthy"}
    except Exception:
        results["vector_db"] = {"status": "unhealthy"}
    try:
        from ingestion.manifest_engine import _catalog_embedder
        vector = await _catalog_embedder().embed_query("health check")
        results["embedding"] = {"status": "healthy" if len(vector) == 1024 else "unhealthy",
                                 "dimension": len(vector)}
    except Exception:
        results["embedding"] = {"status": "unhealthy"}
    try:
        from ingestion.shop_catalog import get_catalog_connector
        await get_catalog_connector().fetch_page(page=1, limit=1)
        results["stores_api"] = {"status": "healthy"}
    except Exception:
        results["stores_api"] = {"status": "unhealthy"}
    return {"status": "healthy" if all(v["status"] == "healthy" for v in results.values()) else "degraded",
            "checks": results}


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

        run = await session.scalar(select(IngestionRun).where(
            IngestionRun.job_id == job_id, IngestionRun.tenant_id == staff.tenant_id
        ))
        payload = {
            "job_id": job.job_id,
            "tenant_id": job.tenant_id,
            "source_type": job.source_type,
            "status": "succeeded" if job.status == "completed" else job.status,
            "progress_pct": job.progress_pct,
            "error_message": job.error_message,
            "stats": job.stats,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "run_id": run.run_id if run else None,
        }
        live_progress = catalog_job_progress.get(job_id)
        if live_progress and job.status in ("queued", "running"):
            payload.update(live_progress)
        return payload


@router.get("/catalog/runs")
async def list_catalog_runs(
    limit: int = Query(20, ge=1, le=100),
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    async with get_async_session(staff.tenant_id) as session:
        stmt = (
            select(IngestionRun, IngestionJob.status)
            .outerjoin(IngestionJob, IngestionJob.job_id == IngestionRun.job_id)
            .where(IngestionRun.tenant_id == staff.tenant_id)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        results = []
        needs_commit = False
        for run_row, job_status in rows:
            eff_status = run_row.status
            if job_status and job_status in ("failed", "cancelled", "completed", "succeeded") and eff_status in ("queued", "running"):
                eff_status = "succeeded" if job_status == "completed" else job_status
                run_row.status = eff_status
                if not run_row.finished_at:
                    run_row.finished_at = datetime.now(timezone.utc)
                needs_commit = True
            results.append({
                "run_id": run_row.run_id,
                "job_id": run_row.job_id,
                "status": eff_status,
                "started_at": run_row.started_at.isoformat() if run_row.started_at else None,
                "finished_at": run_row.finished_at.isoformat() if run_row.finished_at else None,
                "promoted_version_id": run_row.promoted_version_id,
                "stats": run_row.stats,
                "errors": run_row.errors,
                "logs": run_row.logs,
            })
        if needs_commit:
            try:
                await session.commit()
            except Exception:
                pass
        return results


@router.get("/catalog/runs/{run_id}")
async def get_catalog_run(
    run_id: str,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """Retrieve details and structured logs for an individual ingestion run."""
    async with get_async_session(staff.tenant_id) as session:
        run = await session.scalar(select(IngestionRun).where(
            IngestionRun.run_id == run_id, IngestionRun.tenant_id == staff.tenant_id
        ))
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingestion run '{run_id}' not found.")
        return {
            "run_id": run.run_id,
            "job_id": run.job_id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "promoted_version_id": run.promoted_version_id,
            "stats": run.stats,
            "errors": run.errors,
            "logs": run.logs,
        }


@router.post("/catalog/jobs/{job_id}/retry-failed")
async def retry_failed_catalog_items(
    job_id: str,
    background_tasks: BackgroundTasks,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    job = None
    retry_ids: list[str] = []
    try:
        async with get_async_session(staff.tenant_id) as session:
            prior = await session.get(IngestionJob, job_id)
            if not prior or prior.tenant_id != staff.tenant_id or prior.source_type != "catalog":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog job not found.")
            prior_run = await session.scalar(select(IngestionRun).where(
                IngestionRun.job_id == job_id, IngestionRun.tenant_id == staff.tenant_id
            ))
            if not prior_run:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog run details not found.")
            failed_items = (await session.execute(select(IngestionItem).where(
                IngestionItem.run_id == prior_run.run_id, IngestionItem.tenant_id == staff.tenant_id,
                IngestionItem.status == "dead_letter",
            ))).scalars().all()
            retry_ids = sorted({item.product_id for item in failed_items})
            if not retry_ids:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This run has no retryable failed items.")
            active = (await session.execute(select(IngestionJob).where(
                IngestionJob.tenant_id == staff.tenant_id, IngestionJob.source_type == "catalog",
                IngestionJob.status.in_(["queued", "running"]),
            ))).scalars().first()
            if active:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A catalog import is already running.")
            job = IngestionJob(job_id=f"job_cat_{uuid.uuid4().hex[:12]}", tenant_id=staff.tenant_id,
                source_type="catalog", status="queued", progress_pct=0,
                stats={"retry_product_ids": retry_ids, "products_seen": len(retry_ids), "products_processed": 0})
            run = IngestionRun(run_id=f"run_{job.job_id}", job_id=job.job_id,
                tenant_id=staff.tenant_id, status="queued", stats={}, errors=[], logs=[])
            session.add(job)
            session.add(run)
            session.add(AuditEvent(tenant_id=staff.tenant_id, actor_id=staff.staff_id,
                actor_role=staff.role, action="catalog_retry_started", resource_type="ingestion_job",
                resource_id=job.job_id, details={"source_job_id": job_id, "failed_item_count": len(retry_ids)}))
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A catalog import is already running.")
    background_tasks.add_task(_run_catalog_ingestion, staff.tenant_id, staff.staff_id,
                              job.job_id, staff.role, retry_ids)
    return {"job_id": job.job_id, "run_id": run.run_id, "status": "queued",
            "retry_count": len(retry_ids), "stats": job.stats}


@router.post("/catalog/jobs/{job_id}/cancel")
async def cancel_catalog_job(
    job_id: str,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """
    Cancels an active or queued catalog ingestion job.
    Halts staging and preserves active versions.
    """
    manifest_engine.cancel_job(job_id)

    async with get_async_session(staff.tenant_id) as session:
        job = await session.get(IngestionJob, job_id)
        if not job or job.tenant_id != staff.tenant_id or job.source_type != "catalog":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

        run = await session.scalar(select(IngestionRun).where(
            IngestionRun.job_id == job_id,
            IngestionRun.tenant_id == staff.tenant_id,
        ))

        if job.status not in ("queued", "running"):
            if run and run.status in ("queued", "running"):
                run.status = job.status
                run.finished_at = datetime.now(timezone.utc)
                await session.commit()
            return {
                "job_id": job.job_id,
                "run_id": run.run_id if run else None,
                "status": "succeeded" if job.status == "completed" else job.status,
                "message": f"Job '{job_id}' is already in '{job.status}' status.",
            }

        job.status = "cancelled"
        job.error_message = "Ingestion pipeline cancelled by staff."
        job.progress_pct = 100
        if run:
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc)
            run.logs = [*(run.logs or []), {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "run_cancelled",
                "actor_id": staff.staff_id,
                "actor_role": staff.role,
                "reason": "Cancelled by staff.",
            }]

        session.add(AuditEvent(
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="catalog_sync_cancelled",
            resource_type="ingestion_job",
            resource_id=job.job_id,
            details={"run_id": run.run_id if run else None},
        ))
        await session.commit()

        catalog_job_progress[job_id] = {
            "job_id": job.job_id,
            "status": "cancelled",
            "progress_pct": 100,
            "error_message": "Ingestion pipeline cancelled by staff.",
            "stats": dict(job.stats or {}),
        }

        return {
            "job_id": job.job_id,
            "run_id": run.run_id if run else None,
            "status": "cancelled",
            "message": f"Catalog ingestion job '{job_id}' cancelled successfully.",
        }


@router.post("/catalog/cancel")
async def cancel_active_catalog_job(
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """
    Cancels the currently active (running or queued) catalog ingestion job for the tenant.
    """
    async with get_async_session(staff.tenant_id) as session:
        active = (await session.execute(select(IngestionJob).where(
            IngestionJob.tenant_id == staff.tenant_id,
            IngestionJob.source_type == "catalog",
            IngestionJob.status.in_(["queued", "running"]),
        ))).scalars().first()

        if not active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active catalog ingestion job is currently running.",
            )

        active_id = active.job_id

    return await cancel_catalog_job(active_id, staff=staff)


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
