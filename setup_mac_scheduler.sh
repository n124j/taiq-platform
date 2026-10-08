#!/bin/bash
# Sets up a daily 2:00 AM run of the full seed pipeline on macOS (launchd),
# via the project's existing Docker Compose stack:
#     docker compose run --rm job-seeder sh run_seed.sh
# run_seed.sh fetches fresh postings (Adzuna + career-site boards) AND seeds
# any new ones into the database -- see backend/run_seed.sh.
#
# Run from the project ROOT folder (the one with .env and docker-compose.yml):
#     bash setup_mac_scheduler.sh
# Re-running it is safe: it replaces the existing schedule.
#
# This is the sole schedule for the seed pipeline: the job-seeder container's
# own internal cron is deliberately disabled (see docker/crontab) so the
# fetch doesn't run twice a day and exceed Adzuna's 250-calls/day free tier.
set -e

LABEL="us.taiq.jobfeed"
HOUR=2
MINUTE=0

ROOT="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.yml"
ENV_FILE="$ROOT/.env"
LOG="$ROOT/backend/run_seed.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "Project root: $ROOT"
[ -f "$COMPOSE_FILE" ] || { echo "ERROR: not found: $COMPOSE_FILE (run this from the project root)"; exit 1; }
[ -f "$ENV_FILE" ]     || echo "WARNING: no .env at $ENV_FILE -- Adzuna keys and DB credentials must be set some other way."

DOCKER="$(command -v docker || true)"
[ -n "$DOCKER" ] || { echo "ERROR: docker not found. Install Docker Desktop from docker.com."; exit 1; }
echo "Docker:       $DOCKER"
echo "Time zone:    $(date +%Z)  (job runs at ${HOUR}:$(printf %02d $MINUTE) local time)"
echo
echo "NOTE: Docker Desktop must be running (or set to launch at login) for the"
echo "      2am job to succeed, and must have File Sharing access to $ROOT"
echo "      (Docker Desktop > Settings > Resources > File Sharing)."

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DOCKER</string>
    <string>compose</string>
    <string>run</string>
    <string>--rm</string>
    <string>job-seeder</string>
    <string>sh</string>
    <string>run_seed.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Schedule installed: $PLIST"

echo
echo "Next:"
echo "  Test now:      launchctl kickstart gui/$(id -u)/$LABEL && tail -f \"$LOG\""
echo "  Wake the Mac:  sudo pmset repeat wakeorpoweron MTWRFSU 01:55:00"
echo "  Remove:        launchctl bootout gui/$(id -u)/$LABEL"
