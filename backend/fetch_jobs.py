"""
Fetch real jobs from 3 free public APIs (no API key required) and seed into DB.

Sources:
  - The Muse      : ~100 jobs  (5 pages × 20)
  - Remotive      : ~200 jobs  (all remote roles)
  - Arbeitnow     : ~125 jobs  (5 pages × 25)

Usage:
  docker compose exec backend python fetch_jobs.py
"""
import asyncio
import re
import urllib.request
import json
import time
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.core.config import settings
from app.core.database import Base
from app.models.models import Company, Industry, Job, JobType

engine = create_async_engine(settings.DATABASE_URL, echo=False)
Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TalQ/1.0)"}


# ── HTTP helper ───────────────────────────────────────────────────────────────

def get_json(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt == retries:
                print(f"    ⚠️  Failed ({url}): {e}")
                return None
            time.sleep(2)


# ── Text helpers ──────────────────────────────────────────────────────────────

def html_to_text(html):
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def to_slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ── Industry mapping ──────────────────────────────────────────────────────────

INDUSTRY_KEYWORDS = {
    "technology":    ["engineer", "software", "developer", "data", "devops", "cloud",
                      "python", "java", "javascript", "machine learning", "ai", "ml",
                      "backend", "frontend", "fullstack", "full-stack", "it ", "tech",
                      "cyber", "security", "infrastructure", "platform", "saas", "api"],
    "healthcare":    ["health", "medical", "nurse", "doctor", "clinical", "pharma",
                      "biotech", "dental", "hospital", "patient", "therapy"],
    "finance":       ["finance", "accounting", "fintech", "investment", "banking",
                      "equity", "capital", "analyst", "audit", "tax", "insurance"],
    "marketing":     ["marketing", "growth", "seo", "content", "brand", "social media",
                      "copywriter", "advertising", "pr ", "communications", "sales",
                      "business development", "account executive"],
    "education":     ["education", "teacher", "tutor", "learning", "curriculum",
                      "instructor", "trainer", "e-learning", "edtech"],
    "legal":         ["legal", "attorney", "lawyer", "counsel", "paralegal", "compliance"],
    "engineering":   ["mechanical", "electrical", "civil", "structural", "chemical",
                      "aerospace", "manufacturing engineer", "process engineer"],
    "logistics":     ["logistics", "supply chain", "warehouse", "operations", "fleet",
                      "shipping", "procurement", "inventory"],
    "manufacturing": ["manufacturing", "production", "assembly", "quality control",
                      "factory", "plant manager"],
    "retail":        ["retail", "merchandising", "store manager", "e-commerce",
                      "buyer", "fashion", "consumer goods"],
}


def guess_industry(text):
    text = text.lower()
    scores = {slug: 0 for slug in INDUSTRY_KEYWORDS}
    for slug, keywords in INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[slug] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "technology"


def map_job_type(text):
    t = text.lower()
    if "intern" in t:
        return JobType.internship
    if "part" in t or "part-time" in t:
        return JobType.part_time
    if "contract" in t or "freelance" in t:
        return JobType.contract
    if "temp" in t:
        return JobType.temporary
    return JobType.full_time


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_muse(pages=5):
    """The Muse: 20 jobs/page, free, no key."""
    jobs = []
    for page in range(1, pages + 1):
        data = get_json(f"https://www.themuse.com/api/public/jobs?page={page}&descending=true")
        if not data:
            break
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            locations = r.get("locations", [])
            location  = locations[0].get("name", "Remote") if locations else "Remote"
            contents  = html_to_text(r.get("contents", ""))
            categories = [c.get("name", "") for c in r.get("categories", []) if c.get("name")]
            levels     = [l.get("name", "") for l in r.get("levels", []) if l.get("name")]
            combo      = " ".join(categories + levels) + " " + r.get("name", "")
            jobs.append({
                "source":       "muse",
                "title":        r.get("name", "").strip(),
                "company":      r.get("company", {}).get("name", "Unknown").strip(),
                "location":     location,
                "remote":       "remote" in location.lower() or not locations,
                "description":  contents,
                "job_type":     map_job_type(combo),
                "industry":     guess_industry(combo),
                "skills":       categories[:8],
                "salary_min":   None,
                "salary_max":   None,
            })
        print(f"  📄 The Muse page {page}: {len(results)} jobs")
        time.sleep(0.5)
    return jobs


def fetch_remotive():
    """Remotive: all remote jobs, free, no key."""
    data = get_json("https://remotive.com/api/remote-jobs")
    if not data:
        return []
    jobs = []
    for r in data.get("jobs", []):
        salary_min, salary_max = None, None
        sal = r.get("salary", "") or ""
        m = re.findall(r"\$?([\d,]+)k?", sal.lower())
        if len(m) >= 2:
            try:
                salary_min = float(m[0].replace(",", "")) * (1000 if "k" in sal.lower() else 1)
                salary_max = float(m[1].replace(",", "")) * (1000 if "k" in sal.lower() else 1)
            except Exception:
                pass

        title    = r.get("title", "").strip()
        company  = r.get("company_name", "Unknown").strip()
        category = r.get("category", "")
        tags     = r.get("tags", []) or []
        combo    = f"{title} {category} {' '.join(tags)}"
        desc     = html_to_text(r.get("description", ""))

        jobs.append({
            "source":      "remotive",
            "title":       title,
            "company":     company,
            "location":    r.get("candidate_required_location", "Worldwide") or "Worldwide",
            "remote":      True,
            "description": desc,
            "job_type":    map_job_type(r.get("job_type", "")),
            "industry":    guess_industry(combo),
            "skills":      tags[:8],
            "salary_min":  salary_min,
            "salary_max":  salary_max,
        })
    print(f"  📄 Remotive: {len(jobs)} jobs")
    return jobs


def fetch_arbeitnow(pages=5):
    """Arbeitnow: 25 jobs/page, free, no key."""
    jobs = []
    for page in range(1, pages + 1):
        data = get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        if not data:
            break
        results = data.get("data", [])
        if not results:
            break
        for r in results:
            tags  = r.get("tags", []) or []
            title = r.get("title", "").strip()
            combo = f"{title} {' '.join(tags)}"
            desc  = html_to_text(r.get("description", ""))
            jobs.append({
                "source":      "arbeitnow",
                "title":       title,
                "company":     r.get("company_name", "Unknown").strip(),
                "location":    r.get("location", "Remote") or "Remote",
                "remote":      r.get("remote", False),
                "description": desc,
                "job_type":    map_job_type(r.get("job_types", [""])[0] if r.get("job_types") else ""),
                "industry":    guess_industry(combo),
                "skills":      tags[:8],
                "salary_min":  None,
                "salary_max":  None,
            })
        print(f"  📄 Arbeitnow page {page}: {len(results)} jobs")
        time.sleep(0.5)
    return jobs


# ── DB insertion ──────────────────────────────────────────────────────────────

async def insert_jobs(raw_jobs, industry_map, db):
    company_cache = {}
    inserted = skipped = 0

    for r in raw_jobs:
        title       = r["title"]
        company_name = r["company"]

        if not title or not company_name:
            continue

        ind_id = industry_map.get(r["industry"], industry_map.get("technology"))

        # Upsert company
        if company_name not in company_cache:
            company = await db.scalar(select(Company).where(Company.name == company_name))
            if not company:
                slug_co = to_slug(company_name)
                # ensure unique slug
                existing = await db.scalar(select(Company).where(Company.slug == slug_co))
                if existing:
                    slug_co = f"{slug_co}-{r['source']}"
                company = Company(
                    name=company_name,
                    slug=slug_co,
                    description=f"{company_name} is hiring on TalQ.",
                    industry_id=ind_id,
                    is_verified=True,
                    headquarters=r["location"],
                )
                db.add(company)
                await db.flush()
            company_cache[company_name] = company.id
        company_id = company_cache[company_name]

        # Skip duplicates
        existing_job = await db.scalar(
            select(Job).where(Job.title == title, Job.company_id == company_id)
        )
        if existing_job:
            skipped += 1
            continue

        # Unique slug
        job_slug = f"{to_slug(title)}-{company_id}"
        if await db.scalar(select(Job).where(Job.slug == job_slug)):
            job_slug = f"{job_slug}-{inserted}"

        job = Job(
            company_id=company_id,
            industry_id=ind_id,
            title=title,
            slug=job_slug,
            description=r["description"] or f"Exciting opportunity at {company_name}.",
            apply_url=r.get("apply_url"),
            location=r["location"] or "Remote",
            remote=r["remote"],
            job_type=r["job_type"],
            salary_min=r["salary_min"],
            salary_max=r["salary_max"],
            skills_required=r["skills"],
            is_active=True,
            is_featured=False,
        )
        db.add(job)
        inserted += 1

        if inserted % 25 == 0:
            await db.flush()
            print(f"    💾 Flushed {inserted} jobs so far...")

    await db.flush()
    return inserted, skipped


# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    all_jobs = []

    print("\n🌐 Fetching from The Muse (5 pages)...")
    all_jobs += fetch_muse(pages=5)

    print("\n🌐 Fetching from Remotive...")
    all_jobs += fetch_remotive()

    print("\n🌐 Fetching from Arbeitnow (5 pages)...")
    all_jobs += fetch_arbeitnow(pages=5)

    print(f"\n📦 Total raw jobs fetched: {len(all_jobs)}")

    async with Session() as db:
        industries = (await db.scalars(select(Industry))).all()
        if not industries:
            print("❌ No industries in DB. Run seed.py first.")
            return
        industry_map = {ind.slug: ind.id for ind in industries}

        print("\n💾 Inserting into database...")
        inserted, skipped = await insert_jobs(all_jobs, industry_map, db)
        await db.commit()

    print(f"\n🎉 Done!  Inserted: {inserted}  |  Skipped (duplicates): {skipped}")


if __name__ == "__main__":
    asyncio.run(run())
