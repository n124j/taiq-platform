#!/bin/sh
# Fetch fresh job postings and seed them into the database, in one step.
#
# This is the exact two-step pipeline the 2am cron job runs automatically
# (see docker/crontab) -- use this to run it on demand instead of waiting:
#   docker compose exec job-seeder sh run_seed.sh
#   docker compose exec backend     sh run_seed.sh
#
# Step 1 (taiq_jobs_feed.py) only writes output/jobs_latest.json -- no DB
# connection. Step 2 (ingest_feed.py) is what actually inserts rows, and
# needs a working DATABASE_URL, which both of the containers above have.
set -e
cd "$(dirname "$0")"

mkdir -p feed output state

echo "=== 1/2: fetching fresh postings ==="
python taiq_jobs_feed.py

echo
echo "=== 2/2: seeding the database ==="
cp -f output/jobs_latest.json feed/jobs_latest.json
python ingest_feed.py /app/feed
