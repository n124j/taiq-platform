from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Company, User
from app.schemas.schemas import CompanyCreate, CompanyOut, CompanyBrief, CompanyUpdate
from app.api.applications import get_current_user
from app.core.activity import track
from slugify import slugify

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyBrief])
async def list_companies(
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Company).order_by(Company.name).offset(offset).limit(limit)
    if q:
        stmt = select(Company).where(Company.name.ilike(f"%{q}%")).order_by(Company.name).offset(offset).limit(limit)
    companies = (await db.scalars(stmt)).all()
    return [CompanyBrief.model_validate(c) for c in companies]


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    slug = slugify(payload.name)
    existing = await db.scalar(select(Company).where(Company.slug == slug))
    if existing:
        slug = f"{slug}-{current_user.id}"

    company = Company(
        owner_id=current_user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        website=payload.website,
        size=payload.size,
        headquarters=payload.headquarters,
        industry_id=payload.industry_id,
    )
    db.add(company)
    await db.flush()
    await track(db, current_user, "company_created", f"Created company profile: {payload.name}")
    return CompanyOut.model_validate(company)


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(company_id: int, db: AsyncSession = Depends(get_db)):
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyOut.model_validate(company)


@router.put("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: int,
    payload: CompanyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.owner_id != current_user.id and current_user.role.value not in ("admin",):
        raise HTTPException(status_code=403, detail="Not your company")

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
    # is_verified only settable by admin — handled in admin router

    await db.flush()
    await track(db, current_user, "company_updated", f"Updated company profile: {company.name}")
    return CompanyOut.model_validate(company)
