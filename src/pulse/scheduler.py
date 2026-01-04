"""APScheduler instance, shared across jobs."""

from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler(
    timezone="America/Los_Angeles",
    job_defaults={
        "coalesce": True,  # If multiple runs were missed, run once not N times
        "max_instances": 1,  # Don't overlap—if job is running, skip next trigger
        "misfire_grace_time": 3600,  # 1 hour grace period for missed jobs
    },
)
