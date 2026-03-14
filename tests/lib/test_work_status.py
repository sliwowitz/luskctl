# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for agent work-status reading."""

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from terok.lib.containers.work_status import (
    PENDING_PHASE_FILE,
    STATUS_FILE_NAME,
    WORK_STATUS_DISPLAY,
    WORK_STATUSES,
    PendingPhase,
    WorkStatus,
    clear_pending_phase,
    read_pending_phase,
    read_work_status,
    write_pending_phase,
    write_work_status,
)


class TestReadWorkStatus:
    """Tests for read_work_status()."""

    def setup_method(self, method: object):
        """Create a temporary directory for each test."""
        self.tmp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self, method: object):
        """Remove the temporary directory after each test."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_valid_yaml_dict(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text(
            yaml.safe_dump({"status": "coding", "message": "Implementing auth"})
        )
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "coding"
        assert ws.message == "Implementing auth"

    def test_bare_string(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text("testing\n")
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "testing"
        assert ws.message is None

    def test_empty_file(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text("")
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None

    def test_missing_dir(self):
        ws = read_work_status(self.tmp_dir / "nonexistent")
        assert ws.status is None
        assert ws.message is None

    def test_missing_file(self):
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None

    def test_malformed_yaml(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text("{{broken yaml")
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None

    def test_status_only_dict(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text(yaml.safe_dump({"status": "done"}))
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "done"
        assert ws.message is None

    def test_unknown_status_preserved(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text(
            yaml.safe_dump({"status": "thinking-hard", "message": "Deep thoughts"})
        )
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "thinking-hard"
        assert ws.message == "Deep thoughts"

    def test_numeric_yaml_returns_empty(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text("42\n")
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None

    def test_list_yaml_returns_empty(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text("- item1\n- item2\n")
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None

    def test_non_string_status_and_message_normalized(self):
        (self.tmp_dir / STATUS_FILE_NAME).write_text(
            yaml.safe_dump({"status": 123, "message": ["a", "b"]})
        )
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert ws.message is None


class TestWorkStatusVocabulary:
    """Tests for WORK_STATUSES and WORK_STATUS_DISPLAY consistency."""

    def test_all_statuses_have_display(self):
        for status in WORK_STATUSES:
            assert status in WORK_STATUS_DISPLAY, f"Missing display for {status}"

    def test_all_display_have_status(self):
        for status in WORK_STATUS_DISPLAY:
            assert status in WORK_STATUSES, f"Display entry without status: {status}"

    def test_vocabulary_completeness(self):
        expected = {
            "planning",
            "coding",
            "testing",
            "debugging",
            "reviewing",
            "documenting",
            "done",
            "blocked",
            "error",
        }
        assert set(WORK_STATUSES.keys()) == expected

    def test_display_has_emoji_and_label(self):
        for status, info in WORK_STATUS_DISPLAY.items():
            assert info.label
            assert info.emoji
            assert "\ufe0f" not in info.emoji, f"VS16 found in emoji for {status}"


class TestWorkStatusDataclass:
    """Tests for WorkStatus dataclass."""

    def test_defaults(self):
        ws = WorkStatus()
        assert ws.status is None
        assert ws.message is None

    def test_frozen(self):
        ws = WorkStatus(status="coding")
        with pytest.raises(AttributeError):
            ws.status = "testing"  # type: ignore[misc]


class TestWriteWorkStatus:
    """Tests for write_work_status()."""

    def setup_method(self, method: object):
        """Create a temporary directory for each test."""
        self.tmp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self, method: object):
        """Remove the temporary directory after each test."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_creates_file(self):
        write_work_status(self.tmp_dir, "testing")
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "testing"
        assert ws.message is None

    def test_creates_file_with_message(self):
        write_work_status(self.tmp_dir, "coding", message="Writing auth")
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "coding"
        assert ws.message == "Writing auth"

    def test_overwrites_existing(self):
        write_work_status(self.tmp_dir, "coding")
        write_work_status(self.tmp_dir, "testing")
        ws = read_work_status(self.tmp_dir)
        assert ws.status == "testing"

    def test_clears_on_none(self):
        write_work_status(self.tmp_dir, "coding")
        write_work_status(self.tmp_dir, None)
        ws = read_work_status(self.tmp_dir)
        assert ws.status is None
        assert not (self.tmp_dir / STATUS_FILE_NAME).exists()

    def test_clears_missing_file_is_noop(self):
        write_work_status(self.tmp_dir, None)
        assert not (self.tmp_dir / STATUS_FILE_NAME).exists()

    def test_clear_does_not_create_parent_dirs(self):
        missing = self.tmp_dir / "does" / "not" / "exist"
        assert not missing.exists()
        write_work_status(missing, None)
        assert not missing.exists()

    def test_creates_parent_dirs(self):
        nested = self.tmp_dir / "a" / "b" / "c"
        write_work_status(nested, "done")
        ws = read_work_status(nested)
        assert ws.status == "done"


class TestPendingPhase:
    """Tests for pending-phase I/O."""

    def setup_method(self, method: object):
        """Create a temporary directory for each test."""
        self.tmp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self, method: object):
        """Remove the temporary directory after each test."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_read_valid(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text(
            yaml.safe_dump({"phase": "testing", "prompt": "Run tests"})
        )
        pp = read_pending_phase(self.tmp_dir)
        assert pp is not None
        assert pp.phase == "testing"
        assert pp.prompt == "Run tests"

    def test_read_missing(self):
        assert read_pending_phase(self.tmp_dir) is None

    def test_read_missing_dir(self):
        assert read_pending_phase(self.tmp_dir / "nonexistent") is None

    def test_read_malformed(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text("{{broken")
        assert read_pending_phase(self.tmp_dir) is None

    def test_read_no_phase_key(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text(yaml.safe_dump({"prompt": "just a prompt"}))
        assert read_pending_phase(self.tmp_dir) is None

    def test_read_non_dict(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text("bare string\n")
        assert read_pending_phase(self.tmp_dir) is None

    def test_read_missing_prompt_defaults_empty(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text(yaml.safe_dump({"phase": "coding"}))
        pp = read_pending_phase(self.tmp_dir)
        assert pp is not None
        assert pp.phase == "coding"
        assert pp.prompt == ""

    def test_read_non_string_phase_and_prompt(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text(
            yaml.safe_dump({"phase": 123, "prompt": ["x"]})
        )
        assert read_pending_phase(self.tmp_dir) is None

    def test_read_non_string_prompt_only(self):
        (self.tmp_dir / PENDING_PHASE_FILE).write_text(
            yaml.safe_dump({"phase": "coding", "prompt": {"nested": True}})
        )
        assert read_pending_phase(self.tmp_dir) is None

    def test_write_and_read(self):
        write_pending_phase(self.tmp_dir, "reviewing", "Review changes")
        pp = read_pending_phase(self.tmp_dir)
        assert pp is not None
        assert pp.phase == "reviewing"
        assert pp.prompt == "Review changes"

    def test_write_rejects_empty_phase(self):
        with pytest.raises(ValueError):
            write_pending_phase(self.tmp_dir, "", "Run tests")

    def test_write_rejects_non_string_phase(self):
        with pytest.raises(ValueError):
            write_pending_phase(self.tmp_dir, 123, "Run tests")  # type: ignore[arg-type]

    def test_write_rejects_non_string_prompt(self):
        with pytest.raises(ValueError):
            write_pending_phase(self.tmp_dir, "testing", {"x": 1})  # type: ignore[arg-type]

    def test_write_creates_parent_dirs(self):
        nested = self.tmp_dir / "a" / "b"
        write_pending_phase(nested, "testing", "Run tests")
        pp = read_pending_phase(nested)
        assert pp is not None
        assert pp.phase == "testing"

    def test_clear(self):
        write_pending_phase(self.tmp_dir, "testing", "Run tests")
        clear_pending_phase(self.tmp_dir)
        assert read_pending_phase(self.tmp_dir) is None
        assert not (self.tmp_dir / PENDING_PHASE_FILE).exists()

    def test_clear_missing_is_noop(self):
        clear_pending_phase(self.tmp_dir)
        assert not (self.tmp_dir / PENDING_PHASE_FILE).exists()

    def test_frozen(self):
        pp = PendingPhase(phase="testing", prompt="Run tests")
        with pytest.raises(AttributeError):
            pp.phase = "coding"  # type: ignore[misc]
