"""Auto-import all job modules to register them with the scheduler."""

from pulse.jobs import restic
from pulse.jobs import hud
from pulse.jobs import solitude_next
from pulse.jobs import capsule
from pulse.jobs import system_prompt
from pulse.jobs import today
from pulse.jobs import to_self

__all__ = ["restic", "hud", "solitude_next", "capsule", "system_prompt", "today", "to_self"]
