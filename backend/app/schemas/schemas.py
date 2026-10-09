from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Any
from app.models.models import UserRole, JobType, ApplicationStatus


# ── Auth ──────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.candidate

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    phone: str | None = None
    role: UserRole
    avatar_url: str | None
    is_active: bool
    is_email_verified: bool = False
    created_at: datetime
    model_config = {"from_attributes": True}

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class UserAdminOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    phone: str | None = None
    role: UserRole
    is_active: bool
    is_email_verified: bool = False
    created_at: datetime
    model_config = {"from_attributes": True}

class ActivityLogOut(BaseModel):
    id: int
    action: str
    description: str
    extra: dict = {}
    created_at: datetime
    model_config = {"from_attributes": True}

class ActivityLogWithUser(BaseModel):
    id: int
    action: str
    description: str
    extra: dict = {}
    created_at: datetime
    user: "UserAdminOut | None" = None
    model_config = {"from_attributes": True}


# ── Jobs ──────────────────────────────────────────────────────────────────────
class JobCreate(BaseModel):
    title: str
    description: str
    requirements: str | None = None
    benefits: str | None = None
    apply_url: str | None = None
    location: str
    remote: bool = False
    job_type: JobType = JobType.full_time
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    skills_required: list[str] = []
    industry_id: int | None = None
    company_name: str | None = None   # used to auto-create company if none exists
    company_id: int | None = None     # use a specific existing company

class JobOut(BaseModel):
    id: int
    title: str
    slug: str
    description: str
    requirements: str | None
    benefits: str | None
    apply_url: str | None
    location: str
    remote: bool
    job_type: JobType
    salary_min: Decimal | None
    salary_max: Decimal | None
    skills_required: list[Any]
    is_featured: bool
    views: int
    created_at: datetime
    company: "CompanyBrief | None"
    model_config = {"from_attributes": True}

class JobListOut(BaseModel):
    jobs: list[JobOut]
    total: int
    page: int
    pages: int


# ── Company ───────────────────────────────────────────────────────────────────
class CompanyCreate(BaseModel):
    name: str
    description: str | None = None
    website: str | None = None
    size: str | None = None
    headquarters: str | None = None
    industry_id: int | None = None

class CompanyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    website: str | None = None
    size: str | None = None
    headquarters: str | None = None
    industry_id: int | None = None
    is_verified: bool | None = None

class CompanyBrief(BaseModel):
    id: int
    name: str
    logo_url: str | None
    headquarters: str | None
    is_verified: bool
    model_config = {"from_attributes": True}

class CompanyOut(CompanyBrief):
    description: str | None
    website: str | None
    size: str | None

class CompanyAdminOut(CompanyOut):
    id: int
    founded_year: int | None = None
    job_count: int = 0
    created_at: datetime | None = None
    model_config = {"from_attributes": True}


# ── Applications ──────────────────────────────────────────────────────────────
class ApplicationCreate(BaseModel):
    job_id: int
    cover_letter: str | None = None
    resume_url: str | None = None
    referral_source: str | None = None
    referral_email: str | None = None

class ApplicationOut(BaseModel):
    id: int
    status: ApplicationStatus
    cover_letter: str | None
    applied_at: datetime
    job: JobOut | None
    model_config = {"from_attributes": True}


# ── Blog ──────────────────────────────────────────────────────────────────────
class BlogPostOut(BaseModel):
    id: int
    title: str
    slug: str
    excerpt: str | None
    cover_image: str | None
    cover_emoji: str | None = None
    category: str | None
    tags: list[Any]
    reading_time_minutes: int | None = None
    published_at: datetime | None
    model_config = {"from_attributes": True}

class BlogPostDetail(BlogPostOut):
    content: str | None
    author_name: str | None = None


# ── Misc ──────────────────────────────────────────────────────────────────────
class IndustryOut(BaseModel):
    id: int
    name: str
    slug: str
    icon: str | None
    model_config = {"from_attributes": True}

class TestimonialOut(BaseModel):
    id: int
    name: str
    role: str | None
    company: str | None
    avatar_url: str | None
    content: str
    rating: int
    model_config = {"from_attributes": True}

class StatsOut(BaseModel):
    total_jobs: int
    total_companies: int
    total_candidates: int
    placements_this_month: int

class SearchQuery(BaseModel):
    q: str | None = None
    location: str | None = None
    job_type: JobType | None = None
    remote: bool | None = None
    industry_id: int | None = None
    salary_min: Decimal | None = None
    page: int = 1
    limit: int = 20


# ── Site Settings ─────────────────────────────────────────────────────────────
class SiteSettingsOut(BaseModel):
    mode: str
    construction_title: str | None = "We Are Building Something Great"
    construction_message: str | None = "TaIQ is currently undergoing maintenance."
    construction_eta: str | None = ""
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}

class SiteSettingsUpdate(BaseModel):
    mode: str  # "live" or "construction"
    construction_title: str | None = None
    construction_message: str | None = None
    construction_eta: str | None = None


# ── Candidate / Employer views ─────────────────────────────────────────────────
class CandidateBrief(BaseModel):
    id: int
    full_name: str | None
    email: str
    avatar_url: str | None
    model_config = {"from_attributes": True}

class EmployerApplicationOut(BaseModel):
    id: int
    status: ApplicationStatus
    applied_at: datetime
    job: JobOut | None
    candidate: CandidateBrief | None
    model_config = {"from_attributes": True}

class SavedJobOut(BaseModel):
    id: int
    saved_at: datetime
    job: JobOut | None
    model_config = {"from_attributes": True}
