# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""The TUI entry point wires unified logging to a file, never stderr.

[`main`][terok.tui.app.main] must route logging through
[`configure`][terok_util.configure] with a ``stream=`` pointed at the
``terok.log`` file — a stderr ``StreamHandler`` would paint over the Textual
screen.  These smoke tests stub the actual launch (`_run_tui`) so no TUI or
tmux session ever starts.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from terok.lib.util.logging_utils import _terok_log_path
from terok.tui import app

pytestmark = pytest.mark.skipif(not app._HAS_TEXTUAL, reason="requires textual")


def test_main_configures_logging_to_file_then_runs() -> None:
    """``main`` sends logging to the terok.log file stream, then launches the TUI."""
    with (
        patch("sys.argv", ["terok"]),
        patch("terok_util.configure") as configure,
        patch.object(app, "_run_tui") as run_tui,
        patch.object(app, "_launch_in_tmux") as launch_tmux,
    ):
        app.main()

    run_tui.assert_called_once()
    launch_tmux.assert_not_called()
    configure.assert_called_once()
    kwargs = configure.call_args.kwargs
    assert kwargs["identifier"] == "terok"
    # Routed to the terok.log file — a real writable stream, not stderr.
    assert kwargs["stream"].name == str(_terok_log_path())


def test_main_creates_the_log_parent_directory() -> None:
    """The log directory is materialised before the stream opens."""
    log_path = _terok_log_path()
    assert not log_path.parent.exists()  # isolated tmp HOME starts clean

    with (
        patch("sys.argv", ["terok"]),
        patch.object(app, "_run_tui"),
        patch.object(app, "_launch_in_tmux"),
    ):
        app.main()

    assert log_path.parent.is_dir()
