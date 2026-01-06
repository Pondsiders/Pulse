"""Auto-import all job modules to register them with the scheduler."""

from pulse.jobs import restic
from pulse.jobs import hud

__all__ = ["restic", "hud"]
