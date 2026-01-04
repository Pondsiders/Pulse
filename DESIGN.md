# Pulse Design Document

**Version:** 1.0
**Date:** January 1, 2026
**Status:** Design Phase

---

## Overview

Pulse is Alpha's heartbeat—a systemd service that runs scheduled jobs on the mesh. It ties Pondside infrastructure (backups, maintenance, health checks) into the Linux operating system.

**Philosophy:** Simple, observable, composable. Each job is a self-contained module. No config files to parse. Logfire spans wrap everything for timing and observability.

---

## Architecture

### Core Components

```
Basement/Pulse/
├── src/pulse/
│   ├── __init__.py
│   ├── main.py           # Entry point, scheduler setup, Logfire config
│   ├── scheduler.py      # APScheduler instance, shared across jobs
│   └── jobs/
│       ├── __init__.py   # Auto-imports all job modules
│       ├── restic.py     # Hourly Pondside backup to B2
│       └── healthcheck.py # Periodic health checks (future)
├── pyproject.toml
├── .env                  # Secrets (gitignored, synced via Pondside)
├── pulse.service         # systemd unit file
└── DESIGN.md
```

### Job Registration Pattern

Jobs register themselves by importing the scheduler and decorating functions:

```python
# jobs/restic.py
import subprocess
import logfire
from pulse.scheduler import scheduler

@scheduler.scheduled_job('interval', hours=1, id='backup_pondside')
def backup_pondside():
    """Hourly backup of Pondside to Backblaze B2 via Restic."""
    with logfire.span('pulse.job.restic'):
        result = subprocess.run(
            ['restic', 'backup', '/Volumes/Pondside', ...],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            logfire.error('Restic backup failed', stderr=result.stderr)
            raise RuntimeError(f'Backup failed: {result.stderr}')
        logfire.info('Backup complete', stdout=result.stdout[-500:])
```

Adding a new job = create a new file in `jobs/`, import scheduler, decorate. Done.

---

## Scheduler

Using APScheduler with BlockingScheduler (blocks main thread, simpler for dedicated services):

```python
# scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler(
    timezone='America/Los_Angeles',
    job_defaults={
        'coalesce': True,           # If multiple runs were missed, run once not N times
        'max_instances': 1,         # Don't overlap—if job is running, skip next trigger
        'misfire_grace_time': 3600, # 1 hour grace period for missed jobs
    }
)
```

**Settings:**
- `coalesce=True`: If Pulse was down and missed multiple triggers, only run once when it comes back
- `max_instances=1`: Never run the same job concurrently
- `misfire_grace_time=3600`: If a job was missed by less than 1 hour, still run it

---

## Secrets Management

Two files:

**`.env.op`** — Source of truth, checked into git, contains 1Password refs:
```bash
AWS_ACCESS_KEY_ID="op://Alpha/alpha-postgres-backup/username"
AWS_SECRET_ACCESS_KEY="op://Alpha/alpha-postgres-backup/credential"
RESTIC_PASSWORD="op://Alpha/Pondside Restic Password/password"
LOGFIRE_TOKEN="op://Alpha/Logfire Token/credential"
```

**`.env`** — Generated, gitignored, contains real secrets:
```bash
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
RESTIC_PASSWORD=xxx
LOGFIRE_TOKEN=xxx
```

**Setup flow:**
```bash
cd /Volumes/Pondside/Basement/Pulse
op inject -i .env.op -o .env
# Requires biometric auth (Touch ID / fingerprint)
```

**Security model:**
- `.env.op` is committed (just refs, no secrets)
- `.env` is gitignored, synced via Syncthing (encrypted in transit)
- 1Password is SSOT—rotate secrets there, re-run `op inject`
- Biometric required to generate `.env`

Loaded at startup via `python-dotenv`:
```python
from dotenv import load_dotenv
load_dotenv('/Volumes/Pondside/Basement/Pulse/.env')
```

---

## systemd Integration

### Unit File: `pulse.service`

```ini
[Unit]
Description=Pulse - Alpha's scheduled job runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=alpha
WorkingDirectory=/Volumes/Pondside/Basement/Pulse
ExecStart=/usr/bin/uv run python -m pulse.main
Restart=always
RestartSec=10

# Logging to journald
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pulse

[Install]
WantedBy=multi-user.target
```

### Installation

```bash
# Copy unit file
sudo cp pulse.service /etc/systemd/system/

# Reload, enable, start
sudo systemctl daemon-reload
sudo systemctl enable pulse
sudo systemctl start pulse

# Check status
sudo systemctl status pulse
journalctl -u pulse -f
```

---

## Observability

All jobs wrapped in Logfire spans:

```python
with logfire.span('pulse.job.restic', schedule='hourly'):
    # do the thing
```

This gives us:
- **Timing**: How long does each backup take?
- **Success/failure**: Did it work?
- **Trends**: Is backup getting slower over time?
- **Alerting**: (Future) Notify if backup hasn't run in X hours

Logfire configured at startup:
```python
import logfire
logfire.configure(
    service_name='pulse',
    token=os.getenv('LOGFIRE_TOKEN'),
    send_to_logfire='if-token-present'
)
```

---

## Jobs

### 1. Restic Backup (restic.py)

**Schedule:** Every hour
**Purpose:** Incremental backup of Pondside to Backblaze B2

**What it does:**
1. Run `restic backup /Volumes/Pondside` with exclusions
2. Run `restic forget --keep-hourly 24 --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`
3. Log success/failure to Logfire

**Exclusions** (from backup.exclude or inline):
- `.git/objects` (reconstructible from remotes)
- `node_modules/` (reconstructible from package.json)
- `__pycache__/` (generated)
- `.venv/` (reconstructible)
- Large generated files

**Retention policy:**
- 24 hourly snapshots (1 day of hourly granularity)
- 7 daily snapshots (1 week of daily points)
- 4 weekly snapshots (1 month of weekly points)
- 6 monthly snapshots (6 months of monthly points)

### 2. Health Check (healthcheck.py) - Future

**Schedule:** Every 5 minutes
**Purpose:** Verify services are running, log to Logfire

Could check:
- Cortex API responding
- Eavesdrop proxy working
- Postgres accepting connections
- Disk space adequate

---

## Error Handling

Jobs should:
1. Catch exceptions internally when appropriate
2. Let unexpected exceptions bubble up (APScheduler logs them)
3. Use Logfire to record errors with context

```python
@scheduler.scheduled_job('interval', hours=1)
def backup_pondside():
    with logfire.span('pulse.job.restic') as span:
        try:
            # do backup
            span.set_attribute('status', 'success')
        except subprocess.CalledProcessError as e:
            span.set_attribute('status', 'failed')
            span.set_attribute('error', str(e))
            logfire.error('Backup failed', error=str(e), returncode=e.returncode)
            # Don't re-raise - job "completed" with failure logged
```

---

## Main Entry Point

```python
# main.py
import os
from dotenv import load_dotenv

# Load secrets first
load_dotenv('/Volumes/Pondside/Basement/Pulse/.env')

import logfire
logfire.configure(
    service_name='pulse',
    token=os.getenv('LOGFIRE_TOKEN'),
    send_to_logfire='if-token-present'
)

from pulse.scheduler import scheduler
from pulse import jobs  # Auto-registers all jobs via __init__.py

def main():
    logfire.info('Pulse starting')
    scheduler.start()  # Blocks forever, handles SIGTERM/SIGINT internally

if __name__ == '__main__':
    main()
```

BlockingScheduler handles signals internally—no manual signal handling needed.

---

## Dependencies

```toml
[project]
name = "pulse"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "apscheduler>=3.10",
    "python-dotenv>=1.0",
    "logfire>=0.50",
]
```

---

## Deployment Checklist

1. [x] Create `.env` with S3 credentials and LOGFIRE_TOKEN
2. [ ] Install: `uv sync`
3. [ ] Test locally: `uv run python -m pulse.main`
4. [ ] Copy `pulse.service` to `/etc/systemd/system/`
5. [ ] Enable and start: `sudo systemctl enable --now pulse`
6. [ ] Verify in Logfire that jobs are running
7. [ ] Delete old cron job: `crontab -e` on alpha-pi

---

## Future Possibilities

- **Solitude integration**: Pulse could trigger Alpha's nighttime breathing
- **More jobs**: Database vacuuming, log rotation, cert renewal
- **Alerting**: Notify (email? Discord?) if critical jobs fail
- **Web UI**: Simple status page showing job history (or just use Logfire)

---

## Questions Resolved

1. **Where do secrets live?** → `/Volumes/Pondside/Basement/Pulse/.env`, gitignored, synced
2. **How often does Restic run?** → Hourly
3. **What retention policy?** → 24 hourly, 7 daily, 4 weekly, 6 monthly
4. **User service or system service?** → System service, runs as `alpha` user
5. **How do jobs register?** → Import scheduler, decorate function
6. **Observability?** → Logfire spans wrap every job

---

## Ready to Build

The design is complete. Next step: implement it.

🦆
