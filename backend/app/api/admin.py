"""
Admin API — site settings, mode toggle, user management, and activity audit log.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import logging

from app.core.database import get_db
from app.models.models import SiteSettings, SiteMode, User, UserRole, ActivityLog, Job, Company, Application
from app.schemas.schemas import SiteSettingsOut, SiteSettingsUpdate, UserAdminOut, ActivityLogOut, ActivityLogWithUser, JobOut, EmployerApplicationOut, CompanyAdminOut, CompanyUpdate
from app.api.applications import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Auth helpers ──────────────────────────────────────────────────────────────
def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def get_or_create_settings(db: AsyncSession) -> SiteSettings:
    try:
        s = await db.scalar(select(SiteSettings).where(SiteSettings.id == 1))
        if not s:
            s = SiteSettings(
                id=1,
                mode=SiteMode.live,
                construction_title="We Are Building Something Great",
                construction_message="TaIQ is currently undergoing scheduled maintenance. Back shortly.",
                construction_eta="",
                updated_at=datetime.now(timezone.utc),
            )
            db.add(s)
            await db.flush()
            await db.refresh(s)
        return s
    except Exception as e:
        logger.error(f"get_or_create_settings error: {e}")
        raise


# ── Public: read current mode ─────────────────────────────────────────────────
@router.get("/site-settings", response_model=SiteSettingsOut)
async def get_site_settings(db: AsyncSession = Depends(get_db)):
    s = await get_or_create_settings(db)
    return SiteSettingsOut.model_validate(s)


# ── Admin: update mode + construction content ─────────────────────────────────
@router.put("/site-settings", response_model=SiteSettingsOut)
async def update_site_settings(
    payload: SiteSettingsUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if payload.mode not in ("live", "construction"):
        raise HTTPException(status_code=400, detail=f"Invalid mode '{payload.mode}'.")
    try:
        s = await get_or_create_settings(db)
        s.mode = SiteMode(payload.mode)
        s.updated_by = current_user.id
        s.updated_at = datetime.now(timezone.utc)
        if payload.construction_title is not None:
            s.construction_title = payload.construction_title
        if payload.construction_message is not None:
            s.construction_message = payload.construction_message
        if payload.construction_eta is not None:
            s.construction_eta = payload.construction_eta
        await db.flush()
        await db.refresh(s)
        logger.info(f"Site mode set to '{s.mode.value}' by admin {current_user.email}")
        return SiteSettingsOut.model_validate(s)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_site_settings error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


# ── Admin: platform overview stats ────────────────────────────────────────────
@router.get("/overview")
async def admin_overview(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        total_users        = await db.scalar(select(func.count(User.id))) or 0
        total_jobs         = await db.scalar(select(func.count(Job.id))) or 0
        total_companies    = await db.scalar(select(func.count(Company.id))) or 0
        total_applications = await db.scalar(select(func.count(Application.id))) or 0
        site               = await get_or_create_settings(db)
        return {
            "total_users": total_users,
            "total_jobs": total_jobs,
            "total_companies": total_companies,
            "total_applications": total_applications,
            "site_mode": site.mode.value,
        }
    except Exception as e:
        logger.error(f"admin_overview error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Admin: list users ─────────────────────────────────────────────────────────
@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    q: str | None = Query(None),
    role: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where(or_(User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    if role:
        try:
            stmt = stmt.where(User.role == UserRole(role))
        except ValueError:
            pass
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    users = (await db.scalars(stmt)).all()
    return [UserAdminOut.model_validate(u) for u in users]


# ── Admin: user count ─────────────────────────────────────────────────────────
@router.get("/users/count")
async def count_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total    = await db.scalar(select(func.count(User.id))) or 0
    verified = await db.scalar(select(func.count(User.id)).where(User.is_email_verified == True)) or 0
    return {"total": total, "verified": verified}


# ── Admin: single user's activities ──────────────────────────────────────────
@router.get("/users/{user_id}/activities", response_model=list[ActivityLogOut])
async def get_user_activities(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ActivityLog)
        .where(ActivityLog.user_id == user_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
    )
    logs = (await db.scalars(stmt)).all()
    return [ActivityLogOut.model_validate(l) for l in logs]


# ── Admin: all companies ─────────────────────────────────────────────────────
@router.get("/companies")
async def admin_all_companies(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(
        Company,
        func.count(Job.id).label("job_count")
    ).outerjoin(Job, Job.company_id == Company.id).group_by(Company.id).order_by(Company.name)

    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q}%"))

    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).all()

    result = []
    for company, job_count in rows:
        out = CompanyAdminOut.model_validate(company)
        out.job_count = job_count
        result.append(out)
    return result


# ── Admin: edit company ───────────────────────────────────────────────────────
@router.put("/companies/{company_id}")
async def admin_update_company(
    company_id: int,
    payload: CompanyUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.name is not None:
        company.name = payload.name
    if payload.description is not None:
        company.description = payload.description
    if payload.website is not None:
        company.website = payload.website
    if payload.size is not None:
        company.size = payload.size
    if payload.headquarters is not None:
        company.headquarters = payload.headquarters
    if payload.industry_id is not None:
        company.industry_id = payload.industry_id
    if payload.is_verified is not None:
        company.is_verified = payload.is_verified
    await db.flush()
    return CompanyAdminOut.model_validate(company)


# ── Admin: verify/unverify company ────────────────────────────────────────────
@router.patch("/companies/{company_id}/verify")
async def admin_toggle_verify(
    company_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company.is_verified = not company.is_verified
    await db.flush()
    return {"id": company.id, "is_verified": company.is_verified}


# ── Admin: delete company ─────────────────────────────────────────────────────
@router.delete("/companies/{company_id}", status_code=204)
async def admin_delete_company(
    company_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.delete(company)


# ── Admin: all jobs (platform-wide, optionally filtered by company) ─────────
@router.get("/jobs", response_model=list[JobOut])
async def admin_all_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    company_id: int | None = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Job)
        .options(selectinload(Job.company))
        .order_by(Job.created_at.desc())
    )
    if company_id is not None:
        stmt = stmt.where(Job.company_id == company_id)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    jobs = (await db.scalars(stmt)).all()
    return [JobOut.model_validate(j) for j in jobs]


# ── Admin: all applications (platform-wide) ───────────────────────────────────
@router.get("/applications", response_model=list[EmployerApplicationOut])
async def admin_all_applications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.candidate),
        )
        .order_by(Application.applied_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    apps = (await db.scalars(stmt)).all()
    return [EmployerApplicationOut.model_validate(a) for a in apps]


# ── Admin: toggle user email verification ────────────────────────────────────
@router.patch("/users/{user_id}/toggle-verify", response_model=UserAdminOut)
async def toggle_user_verify(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own verification status")
    user.is_email_verified = not user.is_email_verified
    await db.flush()
    await db.refresh(user)
    action = "verified" if user.is_email_verified else "unverified"
    logger.info(f"Admin {current_user.email} {action} user {user.email}")
    return UserAdminOut.model_validate(user)


# ── Admin: all activities ─────────────────────────────────────────────────────
@router.get("/activities", response_model=list[ActivityLogWithUser])
async def get_all_activities(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ActivityLog)
        .options(selectinload(ActivityLog.user))
        .order_by(ActivityLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    logs = (await db.scalars(stmt)).all()
    result = []
    for l in logs:
        user_out = UserAdminOut.model_validate(l.user) if l.user else None
        result.append(ActivityLogWithUser(
            id=l.id,
            action=l.action,
            description=l.description,
            extra=l.extra or {},
            created_at=l.created_at,
            user=user_out,
        ))
    return result
