"""Auto-import all job modules to register them with the scheduler."""

from pulse.jobs import restic

__all__ = ["restic"]
