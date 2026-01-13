"""Auto-import all job modules to register them with the scheduler."""

from pulse.jobs import restic
from pulse.jobs import hud
from pulse.jobs import solitude_next
from pulse.jobs import capsule

__all__ = ["restic", "hud", "solitude_next", "capsule"]
