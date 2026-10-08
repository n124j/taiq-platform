from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.models import Job, Company, UserRole, Application, ApplicationStatus, User
from app.schemas.schemas import JobCreate, JobOut, EmployerApplicationOut, CompanyOut
from app.api.applications import get_current_user
from app.core.activity import track
from app.core.notify import notify
from slugify import slugify
import uuid

router = APIRouter(prefix="/employer/jobs", tags=["employer"])
employer_router = APIRouter(prefix="/employer", tags=["employer"])


def require_employer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.employer, UserRole.admin):
        raise HTTPException(status_code=403, detail="Employer account required")
    return current_user


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def post_job(
    payload: JobCreate,
    current_user: User = Depends(require_employer),
    db: AsyncSession = Depends(get_db),
):
    # Resolve which company to post under
    if payload.company_id:
        # Caller explicitly specified a company
        company = await db.get(Company, payload.company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        # If unowned, claim it
        if company.owner_id is None:
            company.owner_id = current_user.id
            await db.flush()
    else:
        # Use this employer's owned company, auto-creating if needed
        company = await db.scalar(select(Company).where(Company.owner_id == current_user.id))
        if not company:
            co_name = (payload.company_name or "").strip() or (current_user.full_name or "My Company")
            co_slug = slugify(co_name)
            existing_slug = await db.scalar(select(Company).where(Company.slug == co_slug))
            if existing_slug:
                co_slug = f"{co_slug}-{current_user.id}"
            company = Company(
                owner_id=current_user.id,
                name=co_name,
                slug=co_slug,
                industry_id=payload.industry_id,
            )
            db.add(company)
            await db.flush()
            await track(db, current_user, "company_created", f"Company profile auto-created: {co_name}")

    slug = f"{slugify(payload.title)}-{uuid.uuid4().hex[:6]}"
    job = Job(
        company_id=company.id,
        industry_id=payload.industry_id,
        title=payload.title,
        slug=slug,
        description=payload.description,
        requirements=payload.requirements,
        benefits=payload.benefits,
        location=payload.location,
        remote=payload.remote,
        job_type=payload.job_type,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        skills_required=payload.skills_required,
    )
    db.add(job)
    await db.flush()
    await track(db, current_user, "job_posted", f"Posted job: {payload.title}")

    loaded_job = await db.scalar(
        select(Job).options(selectinload(Job.company)).where(Job.id == job.id)
    )
    return JobOut.model_validate(loaded_job)



@router.get("", response_model=list[JobOut])
async def my_jobs(
    current_user: User = Depends(require_employer),
    db: AsyncSession = Depends(get_db),
):
    company = await db.scalar(select(Company).where(Company.owner_id == current_user.id))
    if not company:
        return []
    jobs = (await db.scalars(
        select(Job)
        .options(selectinload(Job.company))
        .where(Job.company_id == company.id)
        .order_by(Job.created_at.desc())
    )).all()
    return [JobOut.model_validate(j) for j in jobs]


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    current_user: User = Depends(require_employer),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    company = await db.scalar(select(Company).where(Company.owner_id == current_user.id))
    if not company or job.company_id != company.id:
        raise HTTPException(status_code=403, detail="Not your job posting")
    job.is_active = False
    await track(db, current_user, "job_deleted", f"Removed job posting: {job.title}")


@employer_router.get("/applications", response_model=list[EmployerApplicationOut])
async def employer_applications(
    current_user: User = Depends(require_employer),
    db: AsyncSession = Depends(get_db),
):
    company = await db.scalar(select(Company).where(Company.owner_id == current_user.id))
    if not company:
        return []
    stmt = (
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.candidate),
        )
        .join(Job, Application.job_id == Job.id)
        .where(Job.company_id == company.id)
        .order_by(Application.applied_at.desc())
        .limit(50)
    )
    apps = (await db.scalars(stmt)).all()
    return [EmployerApplicationOut.model_validate(a) for a in apps]


STATUS_LABELS = {
    "reviewing": "under review",
    "interview": "moved to interview",
    "offered": "offered a position",
    "rejected": "not selected",
    "applied": "reset to applied",
}


@employer_router.patch("/applications/{app_id}/status")
async def update_application_status(
    app_id: int,
    payload: dict,
    current_user: User = Depends(require_employer),
    db: AsyncSession = Depends(get_db),
):
    new_status = payload.get("status", "")
    try:
        new_status = ApplicationStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}'")

    app = await db.scalar(
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.candidate),
        )
        .where(Application.id == app_id)
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Verify this employer owns the job
    company = await db.scalar(select(Company).where(Company.owner_id == current_user.id))
    if not company or app.job.company_id != company.id:
        raise HTTPException(status_code=403, detail="Not your application")

    app.status = new_status
    await db.flush()
    await track(db, current_user, "application_status_updated",
                f"Updated application #{app_id} to {new_status.value}")

    label = STATUS_LABELS.get(new_status.value, new_status.value)
    await notify(
        db,
        user_id=app.candidate_id,
        type="status_changed",
        title=f"Application update: {app.job.title}",
        message=f"Your application at {app.job.company.name} has been {label}.",
    )
    return EmployerApplicationOut.model_validate(app)
