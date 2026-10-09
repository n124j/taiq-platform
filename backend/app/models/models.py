from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey,
    Enum, DECIMAL, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class UserRole(str, enum.Enum):
    candidate = "candidate"
    employer = "employer"
    admin = "admin"


class JobType(str, enum.Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    temporary = "temporary"
    internship = "internship"


class ApplicationStatus(str, enum.Enum):
    applied = "applied"
    reviewing = "reviewing"
    interview = "interview"
    offered = "offered"
    rejected = "rejected"
    withdrawn = "withdrawn"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    phone = Column(String(50))
    role = Column(Enum(UserRole), default=UserRole.candidate)
    is_active = Column(Boolean, default=True)
    is_email_verified = Column(Boolean, default=False)
    avatar_url = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    profile = relationship("CandidateProfile", back_populates="user", uselist=False)
    company = relationship("Company", back_populates="owner", uselist=False)
    applications = relationship("Application", back_populates="candidate")
    saved_jobs = relationship("SavedJob", back_populates="user")
    notifications = relationship("Notification", back_populates="user", order_by="Notification.created_at.desc()")


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    headline = Column(String(255))
    summary = Column(Text)
    skills = Column(JSON, default=list)
    experience_years = Column(Integer, default=0)
    education = Column(JSON, default=list)
    resume_url = Column(String(500))
    linkedin_url = Column(String(500))
    location = Column(String(255))
    desired_salary_min = Column(DECIMAL(10, 2))
    desired_salary_max = Column(DECIMAL(10, 2))
    open_to_remote = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="profile")


class Industry(Base):
    __tablename__ = "industries"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)
    slug = Column(String(100), unique=True)
    icon = Column(String(50))
    companies = relationship("Company", back_populates="industry")
    jobs = relationship("Job", back_populates="industry")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True)
    description = Column(Text)
    website = Column(String(500))
    logo_url = Column(String(500))
    industry_id = Column(Integer, ForeignKey("industries.id"))
    size = Column(String(50))  # e.g. "50-200"
    founded_year = Column(Integer)
    headquarters = Column(String(255))
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="company")
    industry = relationship("Industry", back_populates="companies")
    jobs = relationship("Job", back_populates="company")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    industry_id = Column(Integer, ForeignKey("industries.id"))
    title = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), unique=True)
    description = Column(Text)
    requirements = Column(Text)
    benefits = Column(Text)
    apply_url = Column(String(2048))
    location = Column(String(255))
    remote = Column(Boolean, default=False)
    job_type = Column(Enum(JobType), default=JobType.full_time)
    salary_min = Column(DECIMAL(10, 2))
    salary_max = Column(DECIMAL(10, 2))
    skills_required = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    views = Column(Integer, default=0)
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company", back_populates="jobs")
    industry = relationship("Industry", back_populates="jobs")
    applications = relationship("Application", back_populates="job")
    saved_by = relationship("SavedJob", back_populates="job")


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    candidate_id = Column(Integer, ForeignKey("users.id"))
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.applied)
    cover_letter = Column(Text)
    resume_url = Column(String(500))
    notes = Column(Text)
    referral_source = Column(String(100))
    referral_email = Column(String(255))
    applied_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    job = relationship("Job", back_populates="applications")
    candidate = relationship("User", back_populates="applications")


class SavedJob(Base):
    __tablename__ = "saved_jobs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))
    saved_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="saved_jobs")
    job = relationship("Job", back_populates="saved_by")


class BlogPost(Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    slug = Column(String(255), unique=True)
    excerpt = Column(Text)
    content = Column(Text)
    cover_image = Column(String(500))
    cover_emoji = Column(String(10))
    author_id = Column(Integer, ForeignKey("users.id"))
    category = Column(String(100))
    tags = Column(JSON, default=list)
    reading_time_minutes = Column(Integer, default=5)
    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    author = relationship("User")


class Testimonial(Base):
    __tablename__ = "testimonials"

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    role = Column(String(255))
    company = Column(String(255))
    avatar_url = Column(String(500))
    content = Column(Text)
    rating = Column(Integer, default=5)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SiteMode(str, enum.Enum):
    live = "live"
    construction = "construction"


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False)
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(String(500), nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")


class SiteSettings(Base):
    """Single-row table storing global site configuration."""
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, default=1)
    mode = Column(Enum(SiteMode), default=SiteMode.live, nullable=False)
    construction_title = Column(String(255), default="We Are Building Something Great")
    construction_message = Column(String(1000), default="TaIQ is currently undergoing scheduled maintenance. Back shortly.")
    construction_eta = Column(String(100), default="")
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
