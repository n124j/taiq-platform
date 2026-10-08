#!/usr/bin/env python3
"""
TaIQ daily job feed: one script, all sources, one JSON file.

SOURCES
  adzuna      Broad US job search API (needs free keys in .env)
  greenhouse  \
  lever        |
  ashby        |  Company career-site feeds (free, no key).
  workable     |  Companies come from MANUAL_COMPANIES below, merged with every
                  company name in the TaIQ database (DB_COMPANIES_* below)
  recruitee    |
  personio    /

Everything is configured in the SETTINGS block near the top of this file.
Adzuna keys can go there, or in an optional .env file next to this script.

FILES CREATED (next to this script)
  output/jobs_latest.json     today's result (point TaIQ at this)
  output/jobs_YYYY-MM-DD.json dated copy of each run
  state/state.json            what was sent before (for dedupe and closed-job detection)
  run.log                     written by the scheduler command

OUTPUT FORMAT
  {
    "generated_at": "...",
    "summary":   {"new": N, "closed": M, "by_source": {...}, "errors": [...]},
    "jobs":      [ ...new jobs since the last run... ],
    "closed_ids":[ ...ids of career-site jobs that disappeared (remove these from TaIQ)... ]
  }

USAGE
  python3 taiq_jobs_feed.py           normal daily run
  python3 taiq_jobs_feed.py --test    quick check: 2 Adzuna calls, first company per platform,
                                      writes output/jobs_test.json, does not touch state
Python 3.8+, standard library only.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# =====================================================================
#  SETTINGS  -  edit this block, then run:  python3 taiq_jobs_feed.py
# =====================================================================
CONFIG = {
    # Adzuna keys. Leave blank to read them from a .env file next to this script.
    "ADZUNA_APP_ID": "",          # the SHORT value (8 characters)
    "ADZUNA_APP_KEY": "",         # the LONG value (32 characters)
    "ADZUNA_ENABLED": "true",     # "false" = skip Adzuna
    "ADZUNA_COUNTRY": "us",
    "ADZUNA_MAX_CALLS": "200",    # free tier: 250/day; 50 jobs per call
    "ADZUNA_WHAT": "",            # keyword filter, blank = all jobs
    "ADZUNA_WHERE": "",           # location filter, blank = whole country

    # After each run, also copy jobs_latest.json here (blank = don't copy).
    # Example for Windows via WSL: "/mnt/c/Users/YourName/TaIQ/jobs_latest.json"
    "COPY_TO": "",

    "SEEN_RETENTION_DAYS": "60",  # how long to remember jobs already sent

    # TaIQ's own API, used to pull company names out of the `companies` table
    # (see DB_COMPANIES_* below). Must be reachable from wherever this script
    # runs -- left blank so the right default is picked automatically: the
    # Docker cron container sets API_BASE=http://backend:8000/api/v1 as an
    # environment variable (see docker-compose.yml); running by hand on your
    # own machine falls back to the nginx port below.
    "API_BASE": "",
}
API_BASE_FALLBACK = "http://localhost:8090/api/v1"

# Companies to pull from each career-site platform.
# The name comes from the company's careers link, e.g.
#   job-boards.greenhouse.io/gitlab  -> "gitlab" under greenhouse
#   jobs.lever.co/palantir           -> "palantir" under lever
#   jobs.ashbyhq.com/ramp            -> "ramp" under ashby
#   apply.workable.com/acme          -> "acme" under workable
#   acme.recruitee.com               -> "acme" under recruitee
#   acme.jobs.personio.de            -> "acme" under personio
# A wrong name just shows "FAILED" for that company in the log; the run continues.
#
# These are hand-verified real board slugs -- kept as a trusted override because
# the TaIQ database (below) has no idea which ATS platform a company actually
# uses, so it can only ever guess.
MANUAL_COMPANIES = {
    "greenhouse": ["gitlab", "airbnb", "stripe"],
    "lever":      ["palantir"],
    "ashby":      ["ramp", "linear"],
    "workable":   [],
    "recruitee":  [],
    "personio":   [],
}

# Also pull every company name out of TaIQ's own `companies` database table
# (via the public GET /api/v1/companies API) and try each one, slugified, on
# the platform(s) listed here. The DB only stores a display name -- it does
# not record which career-site platform (if any) a company publishes jobs on
# -- so most of these guesses will simply fail and log "FAILED"; that's
# expected and harmless (see the note above). Keep this to one or two
# platforms by default, since every extra platform multiplies the number of
# HTTP requests (and run time) by the number of DB companies.
#
# DB_COMPANIES_MAX caps how many DB-sourced slugs get tried per run. Without
# a cap, this grows -- and the run gets slower -- every single day, since
# each run's ingested jobs add new companies for the *next* run to check.
# 400 slugs costs roughly 400 extra seconds (the 1s pause between career-site
# requests) on top of Adzuna, which is fine for a nightly job.
DB_COMPANIES_ENABLED = True
DB_COMPANIES_PLATFORMS = ["greenhouse"]
DB_COMPANIES_MAX = 400
# =====================================================================

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
STATE_FILE = BASE / "state" / "state.json"
ENV_FILE = BASE / ".env"
UA = "TaIQ-jobs-feed/2.0 (+https://taiq.us)"
ATS_PLATFORMS = ["greenhouse", "lever", "ashby", "workable", "recruitee", "personio"]


# ---------------------------------------------------------------- settings
def load_env_file(path):
    """Read KEY=VALUE lines from .env (tolerates Windows line endings, quotes, spaces)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip().replace("\r", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def setting(name, default=""):
    """CONFIG block first; if blank there, fall back to .env / environment."""
    v = str(CONFIG.get(name, "")).strip()
    if v:
        return v
    return os.environ.get(name, default).strip()


# ---------------------------------------------------------------- helpers
def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_get(url, accept="application/json", retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise
    raise last


def get_json(url):
    return json.loads(http_get(url))


TAG_RE = re.compile(r"<[^>]+>")
BLOCK_RE = re.compile(r"</?(p|br|li|ul|ol|div|h[1-6])[^>]*>", re.I)


def to_text(s):
    """HTML (possibly escaped) -> readable plain text."""
    if not s:
        return None
    s = html.unescape(html.unescape(str(s)))
    s = BLOCK_RE.sub("\n", s)
    s = TAG_RE.sub("", s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip() or None


def ms_to_iso(ms):
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def norm_type(s):
    """Map many spellings to: full_time, part_time, contract, temporary, internship."""
    if not s:
        return None
    t = str(s).lower().replace("-", " ").replace("_", " ")
    if "intern" in t:
        return "internship"
    if "temp" in t:
        return "temporary"
    if "contract" in t or "freelance" in t:
        return "contract"
    if "part" in t:
        return "part_time"
    if "full" in t or "permanent" in t:
        return "full_time"
    return None


REMOTE_RE = re.compile(r"\bremote\b|\banywhere\b|work from home|\bwfh\b", re.I)


def guess_remote(*fields):
    return True if any(f and REMOTE_RE.search(str(f)) for f in fields) else None


def job(**kw):
    """Single shared schema for every source."""
    rec = {
        "id": None, "source": None, "source_company": None,
        "title": None, "company": None, "location": None, "remote": None,
        "employment_type": None, "category": None,
        "salary_min": None, "salary_max": None, "salary_currency": None,
        "description": None, "apply_url": None, "posted_at": None,
        "fetched_at": now_iso(), "attribution": None,
    }
    rec.update(kw)
    if rec["remote"] is None:
        rec["remote"] = guess_remote(rec["title"], rec["location"])
    if rec["description"] and len(rec["description"]) > 20000:
        rec["description"] = rec["description"][:20000] + "..."
    return rec


# ---------------------------------------------------------------- Adzuna
def fetch_adzuna(max_calls):
    app_id, app_key = setting("ADZUNA_APP_ID"), setting("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise RuntimeError("Adzuna keys not set: fill ADZUNA_APP_ID / ADZUNA_APP_KEY in the SETTINGS block or in .env")
    country = setting("ADZUNA_COUNTRY", "us")
    what, where = setting("ADZUNA_WHAT"), setting("ADZUNA_WHERE")
    per_page = 50
    out, calls, page = [], 0, 1
    while calls < max_calls:
        params = {"app_id": app_id, "app_key": app_key, "results_per_page": per_page,
                  "sort_by": "date", "max_days_old": 1}
        if what:
            params["what"] = what
        if where:
            params["where"] = where
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?" + urllib.parse.urlencode(params)
        try:
            data = get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise RuntimeError("Adzuna rejected the keys (401). Check ADZUNA_APP_ID (short) and ADZUNA_APP_KEY (long) in .env")
            if calls == 0:
                raise
            print(f"  adzuna: stopped at page {page}: {e}")
            break
        calls += 1
        results = data.get("results", [])
        for j in results:
            loc = (j.get("location") or {}).get("display_name")
            out.append(job(
                id=f"adzuna:{j.get('id')}", source="adzuna",
                title=j.get("title"), company=(j.get("company") or {}).get("display_name"),
                location=loc,
                employment_type=norm_type(j.get("contract_time")) or norm_type(j.get("contract_type")),
                category=(j.get("category") or {}).get("label"),
                salary_min=j.get("salary_min"), salary_max=j.get("salary_max"),
                salary_currency="USD" if country == "us" else None,
                description=to_text(j.get("description")), apply_url=j.get("redirect_url"),
                posted_at=j.get("created"),
                attribution={"label": "Jobs by Adzuna", "url": "https://www.adzuna.com"},
            ))
        if len(results) < per_page:
            break
        page += 1
        time.sleep(2.6)  # free tier: max 25 calls/minute
    print(f"  adzuna: {len(out)} jobs in {calls} calls")
    return out


# ---------------------------------------------------------------- career-site platforms
def fetch_greenhouse(slug):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        depts = j.get("departments") or []
        out.append(job(
            id=f"greenhouse:{slug}:{j.get('id')}", source="greenhouse", source_company=slug,
            title=j.get("title"), company=j.get("company_name") or slug,
            location=(j.get("location") or {}).get("name"),
            category=depts[0].get("name") if depts else None,
            description=to_text(j.get("content")), apply_url=j.get("absolute_url"),
            posted_at=j.get("first_published") or j.get("updated_at"),
        ))
    return out


def fetch_lever(slug):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data:
        cats = j.get("categories") or {}
        sal = j.get("salaryRange") or {}
        wt = (j.get("workplaceType") or "").lower()
        out.append(job(
            id=f"lever:{slug}:{j.get('id')}", source="lever", source_company=slug,
            title=j.get("text"), company=slug, location=cats.get("location"),
            remote=True if wt == "remote" else (False if wt in ("onsite", "on-site") else None),
            employment_type=norm_type(cats.get("commitment")), category=cats.get("team") or cats.get("department"),
            salary_min=sal.get("min"), salary_max=sal.get("max"), salary_currency=sal.get("currency"),
            description=to_text(j.get("descriptionPlain") or j.get("description")),
            apply_url=j.get("hostedUrl") or j.get("applyUrl"), posted_at=ms_to_iso(j.get("createdAt")),
        ))
    return out


def fetch_ashby(slug):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        jid = j.get("id") or j.get("jobUrl")
        out.append(job(
            id=f"ashby:{slug}:{jid}", source="ashby", source_company=slug,
            title=j.get("title"), company=slug, location=j.get("location"),
            remote=j.get("isRemote"), employment_type=norm_type(j.get("employmentType")),
            category=j.get("department") or j.get("team"),
            description=to_text(j.get("descriptionPlain") or j.get("descriptionHtml")),
            apply_url=j.get("jobUrl") or j.get("applyUrl"), posted_at=j.get("publishedAt"),
        ))
    return out


def fetch_workable(slug):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    company = data.get("name") or slug
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x) or None
        out.append(job(
            id=f"workable:{slug}:{j.get('shortcode') or j.get('id')}", source="workable", source_company=slug,
            title=j.get("title"), company=company, location=loc,
            remote=True if j.get("telecommuting") else None,
            employment_type=norm_type(j.get("employment_type")), category=j.get("department"),
            description=to_text(j.get("description")),
            apply_url=j.get("url") or j.get("shortlink") or j.get("application_url"),
            posted_at=j.get("published_on") or j.get("created_at"),
        ))
    return out


def fetch_recruitee(slug):
    data = get_json(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x) or None
        desc = "\n\n".join(x for x in [to_text(j.get("description")), to_text(j.get("requirements"))] if x) or None
        sal = j.get("salary") or {}
        out.append(job(
            id=f"recruitee:{slug}:{j.get('id')}", source="recruitee", source_company=slug,
            title=j.get("title"), company=j.get("company_name") or slug, location=loc,
            remote=True if j.get("remote") else None,
            employment_type=norm_type(j.get("employment_type_code")), category=j.get("department"),
            salary_min=sal.get("min"), salary_max=sal.get("max"), salary_currency=sal.get("currency"),
            description=desc, apply_url=j.get("careers_url") or j.get("careers_apply_url"),
            posted_at=j.get("published_at") or j.get("created_at"),
        ))
    return out


def fetch_personio(slug):
    last_err, text, host = None, None, None
    for h in (f"{slug}.jobs.personio.de", f"{slug}.jobs.personio.com"):
        try:
            text = http_get(f"https://{h}/xml?language=en", accept="application/xml")
            host = h
            break
        except Exception as e:
            last_err = e
    if text is None:
        raise last_err
    root = ET.fromstring(text)
    out = []
    for p in root.iter("position"):
        g = lambda tag: (p.findtext(tag) or "").strip() or None
        parts = []
        for d in p.iter("jobDescription"):
            name, val = d.findtext("name"), to_text(d.findtext("value"))
            if val:
                parts.append(f"{name}\n{val}" if name else val)
        pid = g("id")
        out.append(job(
            id=f"personio:{slug}:{pid}", source="personio", source_company=slug,
            title=g("name"), company=g("subcompany") or slug, location=g("office"),
            employment_type=norm_type(g("schedule")) or norm_type(g("employmentType")),
            category=g("department") or g("recruitingCategory"),
            description="\n\n".join(parts) or None,
            apply_url=f"https://{host}/job/{pid}", posted_at=g("createdAt"),
        ))
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "workable": fetch_workable, "recruitee": fetch_recruitee, "personio": fetch_personio}


def slugify_name(name):
    """Best-effort company-name -> URL-slug, e.g. "Acme, Inc." -> "acme-inc"."""
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


def api_base():
    return setting("API_BASE", API_BASE_FALLBACK).rstrip("/")


def fetch_db_company_slugs(max_count):
    """Up to max_count company names from the TaIQ `companies` table,
    slugified and deduped, via the public GET /api/v1/companies API
    (paginated with limit/offset, ordered alphabetically by the API).
    NOTE: with a cap, the same alphabetical slice gets tried every run --
    good enough since most guesses fail anyway, but it means companies past
    the cap are never checked. Raise DB_COMPANIES_MAX for broader coverage
    at the cost of a longer run."""
    base = api_base()
    limit = 200
    offset = 0
    seen, out = set(), []
    while len(out) < max_count:
        url = f"{base}/companies?limit={limit}&offset={offset}"
        data = get_json(url)
        if not data:
            break
        for c in data:
            slug = slugify_name(c.get("name"))
            if slug and slug not in seen:
                seen.add(slug)
                out.append(slug)
                if len(out) >= max_count:
                    break
        if len(data) < limit:
            break
        offset += limit
    return out


def load_companies():
    """Company slugs to try per ATS platform: MANUAL_COMPANIES (hand-verified
    real board slugs) merged with slugified names pulled from the TaIQ
    database (DB_COMPANIES_PLATFORMS), instead of a single hardcoded list."""
    result = {
        k: [s.strip() for s in MANUAL_COMPANIES.get(k, []) if isinstance(s, str) and s.strip()]
        for k in ATS_PLATFORMS
    }
    if DB_COMPANIES_ENABLED:
        try:
            db_slugs = fetch_db_company_slugs(DB_COMPANIES_MAX)
            print(f"  db companies: {len(db_slugs)} names from {api_base()}")
        except Exception as e:
            db_slugs = []
            print(f"  db companies: FAILED to fetch from {api_base()}: {e}")
        for platform in DB_COMPANIES_PLATFORMS:
            if platform not in result:
                continue
            existing = set(result[platform])
            result[platform] += [s for s in db_slugs if s not in existing]
    return result


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="TaIQ daily job feed")
    ap.add_argument("--test", action="store_true", help="quick check; does not update state")
    args = ap.parse_args()

    load_env_file(ENV_FILE)
    OUT_DIR.mkdir(exist_ok=True)
    STATE_FILE.parent.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    print(f"[{now_iso()}] TaIQ job feed starting{' (TEST MODE)' if args.test else ''}")

    state = {"seen": {}, "ats_active": {}}
    if STATE_FILE.exists():
        try:
            state.update(json.loads(STATE_FILE.read_text()))
        except Exception:
            print("  warning: state file unreadable, starting fresh")
    keep_days = int(setting("SEEN_RETENTION_DAYS", "60"))
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}

    fetched, errors, by_source, closed_ids = [], [], {}, []

    # Adzuna
    if setting("ADZUNA_ENABLED", "true").lower() != "false":
        try:
            got = fetch_adzuna(2 if args.test else int(setting("ADZUNA_MAX_CALLS", "200")))
            fetched += got
            by_source["adzuna"] = len(got)
        except Exception as e:
            errors.append(f"adzuna: {e}")
            print(f"  adzuna: FAILED: {e}")

    # Career-site platforms
    try:
        companies = load_companies()
    except Exception as e:
        companies = {}
        errors.append(str(e))
        print(f"  {e}")
    for platform in ATS_PLATFORMS:
        slugs = companies.get(platform, [])
        if args.test:
            slugs = slugs[:1]
        for slug in slugs:
            key = f"{platform}:{slug}"
            try:
                got = FETCHERS[platform](slug)
            except Exception as e:
                errors.append(f"{key}: {e}")
                print(f"  {key}: FAILED: {e}")
                continue
            fetched += got
            by_source[platform] = by_source.get(platform, 0) + len(got)
            print(f"  {key}: {len(got)} jobs")
            current = {j["id"] for j in got}
            previous = set(state["ats_active"].get(key, []))
            if previous:
                closed_ids += sorted(previous - current)
            if not args.test:
                state["ats_active"][key] = sorted(current)
            time.sleep(1)

    # Dedupe: within this run, and against earlier runs
    new, batch = [], set()
    for j in fetched:
        if not j["id"] or j["id"] in batch or j["id"] in state["seen"]:
            continue
        batch.add(j["id"])
        new.append(j)

    payload = {
        "generated_at": now_iso(),
        "summary": {"new": len(new), "closed": len(closed_ids), "fetched": len(fetched),
                    "by_source": by_source, "errors": errors},
        "jobs": new,
        "closed_ids": closed_ids,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.test:
        out = OUT_DIR / "jobs_test.json"
        out.write_text(text, encoding="utf-8")
        print(f"  TEST: {len(new)} jobs written to {out} (state not changed)")
        return 0

    dated = OUT_DIR / f"jobs_{today}.json"
    dated.write_text(text, encoding="utf-8")
    latest = OUT_DIR / "jobs_latest.json"
    latest.write_text(text, encoding="utf-8")

    for i in batch:
        state["seen"][i] = today
    STATE_FILE.write_text(json.dumps(state))

    # Optional: copy to a folder TaIQ (or Windows) reads from
    copy_to = setting("COPY_TO")
    if copy_to:
        try:
            dest = Path(copy_to)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(latest, dest)
            print(f"  copied to {dest}")
        except Exception as e:
            errors.append(f"copy: {e}")
            print(f"  copy FAILED: {e}")

    # Keep 30 days of dated files
    for f in OUT_DIR.glob("jobs_20*.json"):
        if f.stem[5:] < (dt.date.today() - dt.timedelta(days=30)).isoformat():
            f.unlink()

    print(f"  done: {len(new)} new, {len(closed_ids)} closed, {len(errors)} errors -> {latest}")
    return 0 if not errors or new else 1


if __name__ == "__main__":
    sys.exit(main())
