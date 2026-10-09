from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base
from app.api import auth, jobs, public, applications, companies, employer, profile, admin, parse_job, notifications
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
            # create_all only creates missing tables, not missing columns on
            # tables that already existed before this column was added.
            await conn.execute(text(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_url VARCHAR(2048)"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(50)"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_id VARCHAR(255)"
            ))
            await conn.execute(text(
                "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"
            ))
    except IntegrityError:
        # Another worker already created tables concurrently — safe to ignore
        pass
    logger.info("Database tables ready")
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/v1")
app.include_router(jobs.router,         prefix="/api/v1")
app.include_router(public.router,       prefix="/api/v1")
app.include_router(applications.router, prefix="/api/v1")
app.include_router(companies.router,    prefix="/api/v1")
app.include_router(employer.router,         prefix="/api/v1")
app.include_router(employer.employer_router, prefix="/api/v1")
app.include_router(profile.router,      prefix="/api/v1")
app.include_router(admin.router,        prefix="/api/v1")
app.include_router(parse_job.router,        prefix="/api/v1")
app.include_router(notifications.router,    prefix="/api/v1")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
