"""
One-off backfill: extract apply links that earlier ingestion runs embedded as
plain text in Job.description (e.g. "...\n\nApply here: https://...") into the
new Job.apply_url column, and strip that trailing text back out of the
description.

Usage:
  docker compose exec backend python backfill_apply_url.py
"""
import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.models import Job

engine = create_async_engine(settings.DATABASE_URL, echo=False)
Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

APPLY_LINE_RE = re.compile(r"\n*Apply here:\s*(https?://\S+)\s*$")


async def run():
    async with Session() as db:
        jobs = (await db.scalars(select(Job).where(Job.apply_url.is_(None)))).all()
        updated = 0
        for job in jobs:
            if not job.description:
                continue
            m = APPLY_LINE_RE.search(job.description)
            if not m:
                continue
            job.apply_url = m.group(1)
            job.description = job.description[: m.start()].rstrip()
            updated += 1
        await db.commit()
        print(f"✅ Backfilled apply_url for {updated} of {len(jobs)} job(s) missing it.")


if __name__ == "__main__":
    asyncio.run(run())
