"""
Ingest external job postings from feed/*.json into the database.

Each feed file looks like:
  {"generated_at": "...", "count": N, "jobs": [{"id", "source", "title", "company",
   "location", "remote", "employment_type", "category", "salary_min", "salary_max",
   "salary_currency", "description", "apply_url", "posted_at", "fetched_at",
   "attribution"}, ...]}

Usage:
  docker compose exec backend python ingest_feed.py [path-to-feed-dir]
  (defaults to /app/feed)
"""
import asyncio
import glob
import json
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base
from app.models.models import Company, Industry, Job

from fetch_jobs import guess_industry, map_job_type, html_to_text, to_slug

engine = create_async_engine(settings.DATABASE_URL, echo=False)
Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def load_feed_jobs(feed_dir):
    jobs = []
    for path in sorted(glob.glob(os.path.join(feed_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        file_jobs = data.get("jobs", [])
        print(f"  📄 {os.path.basename(path)}: {len(file_jobs)} jobs")
        jobs.extend(file_jobs)
    return jobs


def trunc(s, n=255):
    """DB columns are VARCHAR(255); some feed values (e.g. a job listing every
    US state as its location) run far longer, which would otherwise fail the
    whole insert batch."""
    s = s or ""
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def normalize(raw):
    title = trunc((raw.get("title") or "").strip())
    company = trunc((raw.get("company") or "Unknown").strip())
    category = raw.get("category") or ""
    combo = f"{title} {category}"
    location = trunc((raw.get("location") or "Remote").strip())
    remote = raw.get("remote")
    if remote is None:
        remote = "remote" in location.lower()
    description = html_to_text(raw.get("description") or "")
    apply_url = raw.get("apply_url")

    return {
        "title": title,
        "company": company,
        "location": location or "Remote",
        "remote": bool(remote),
        "description": description,
        "apply_url": apply_url,
        "job_type": map_job_type(raw.get("employment_type") or ""),
        "industry": guess_industry(combo),
        "skills": [category] if category else [],
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "source": raw.get("source", "feed"),
    }


async def insert_jobs(raw_jobs, industry_map, db):
    company_cache = {}
    inserted = skipped = 0

    for r in raw_jobs:
        norm = normalize(r)
        title = norm["title"]
        company_name = norm["company"]
        if not title or not company_name:
            skipped += 1
            continue

        ind_id = industry_map.get(norm["industry"], industry_map.get("technology"))

        if company_name not in company_cache:
            company = await db.scalar(select(Company).where(Company.name == company_name))
            if not company:
                slug_co = trunc(to_slug(company_name), 240)
                if await db.scalar(select(Company).where(Company.slug == slug_co)):
                    slug_co = trunc(f"{slug_co}-{norm['source']}")
                company = Company(
                    name=company_name,
                    slug=slug_co,
                    description=f"{company_name} is hiring on TaIQ.",
                    industry_id=ind_id,
                    is_verified=True,
                    headquarters=norm["location"],
                )
                db.add(company)
                await db.flush()
            company_cache[company_name] = company.id
        company_id = company_cache[company_name]

        existing_job = await db.scalar(
            select(Job).where(Job.title == title, Job.company_id == company_id)
        )
        if existing_job:
            skipped += 1
            continue

        job_slug = trunc(f"{to_slug(title)}-{company_id}", 240)
        if await db.scalar(select(Job).where(Job.slug == job_slug)):
            job_slug = trunc(f"{job_slug}-{inserted}-{company_id}")

        job = Job(
            company_id=company_id,
            industry_id=ind_id,
            title=title,
            slug=job_slug,
            description=norm["description"] or f"Exciting opportunity at {company_name}.",
            apply_url=norm["apply_url"],
            location=norm["location"],
            remote=norm["remote"],
            job_type=norm["job_type"],
            salary_min=norm["salary_min"],
            salary_max=norm["salary_max"],
            skills_required=norm["skills"],
            is_active=True,
            is_featured=False,
        )
        db.add(job)
        inserted += 1

        if inserted % 50 == 0:
            await db.commit()
            print(f"    💾 Committed {inserted} jobs so far...")

    await db.commit()
    return inserted, skipped


async def run(feed_dir):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print(f"\n📂 Loading feed files from {feed_dir}...")
    raw_jobs = load_feed_jobs(feed_dir)
    print(f"📦 Total raw jobs loaded: {len(raw_jobs)}")

    async with Session() as db:
        industries = (await db.scalars(select(Industry))).all()
        if not industries:
            print("❌ No industries in DB. Run seed.py first.")
            return
        industry_map = {ind.slug: ind.id for ind in industries}

        print("\n💾 Inserting into database...")
        inserted, skipped = await insert_jobs(raw_jobs, industry_map, db)
        await db.commit()

    print(f"\n🎉 Done!  Inserted: {inserted}  |  Skipped (duplicates/invalid): {skipped}")


if __name__ == "__main__":
    feed_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/feed"
    asyncio.run(run(feed_dir))
