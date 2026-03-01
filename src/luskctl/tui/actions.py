# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""ActionsMixin — combined mixin re-exported from focused submodules.

This module provides backward-compatible access to the ``ActionsMixin``
class, which is composed from :class:`ProjectActionsMixin` and
:class:`TaskActionsMixin`.  New code should import the specific mixin
it needs from ``project_actions`` or ``task_actions`` directly.
"""

from .project_actions import ProjectActionsMixin
from .task_actions import TaskActionsMixin


class ActionsMixin(ProjectActionsMixin, TaskActionsMixin):
    """Combined action handler mixin for the LuskTUI application.

    Inherits from :class:`ProjectActionsMixin` (project infrastructure,
    shared helpers) and :class:`TaskActionsMixin` (task lifecycle operations).
    """
