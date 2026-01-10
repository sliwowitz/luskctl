import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib.git_gate import (
    compare_gate_vs_upstream,
    find_projects_sharing_gate,
    get_gate_branch_head,
    get_gate_last_commit,
    get_upstream_head,
    init_project_gate,
    sync_gate_branches,
    validate_gate_upstream_match,
)
from test_utils import write_project


class GitGateTests(unittest.TestCase):
    def test_init_project_gate_ssh_requires_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            envs_dir = base / "envs"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj6"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: git@github.com:org/repo.git\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with (
                unittest.mock.patch.dict(
                    os.environ,
                    {
                        "CODEXCTL_CONFIG_DIR": str(config_root),
                        "CODEXCTL_CONFIG_FILE": str(config_file),
                        "CODEXCTL_STATE_DIR": str(state_dir),
                    },
                ),
                self.assertRaises(SystemExit),
            ):
                init_project_gate(project_id)

    def test_init_project_gate_https_clone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj7"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch("codexctl.lib.git_gate.subprocess.run") as run_mock:
                    run_mock.return_value.returncode = 0
                    result = init_project_gate(project_id)

                self.assertTrue(result["created"])
                self.assertIn("path", result)
                self.assertEqual(result["upstream_url"], "https://example.com/repo.git")

                call = run_mock.call_args
                self.assertIsNotNone(call)
                args, kwargs = call
                self.assertEqual(args[0][:3], ["git", "clone", "--mirror"])
                self.assertIn("env", kwargs)

    def test_get_gate_last_commit_no_gate(self) -> None:
        """Test get_gate_last_commit when gate doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj8"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                result = get_gate_last_commit(project_id)
                self.assertIsNone(result)

    def test_get_gate_last_commit_with_gate(self) -> None:
        """Test get_gate_last_commit when gate exists."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj9"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock the git log command to return sample commit data
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = (
                    "abc123def456|2023-01-01 12:00:00 +0000|Test commit message|John Doe\n"
                )

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_gate_last_commit(project_id)

                self.assertIsNotNone(result)
                self.assertEqual(result["commit_hash"], "abc123def456")
                self.assertEqual(result["commit_date"], "2023-01-01 12:00:00 +0000")
                self.assertEqual(result["commit_message"], "Test commit message")
                self.assertEqual(result["commit_author"], "John Doe")

    # Tests for get_upstream_head
    def test_get_upstream_head_success(self) -> None:
        """Test successful upstream head query."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj10"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock successful git ls-remote
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "abc123def456789\trefs/heads/main\n"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_upstream_head(project_id)

                self.assertIsNotNone(result)
                self.assertEqual(result["commit_hash"], "abc123def456789")
                self.assertEqual(result["ref_name"], "refs/heads/main")
                self.assertEqual(result["upstream_url"], "https://example.com/repo.git")

    def test_get_upstream_head_no_upstream_url(self) -> None:
        """Test get_upstream_head when project has no upstream URL."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj11"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                result = get_upstream_head(project_id)
                self.assertIsNone(result)

    def test_get_upstream_head_network_failure(self) -> None:
        """Test get_upstream_head when network query fails."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj12"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock failed git ls-remote
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 128
                mock_result.stderr = "fatal: could not read from remote repository"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_upstream_head(project_id)

                self.assertIsNone(result)

    def test_get_upstream_head_branch_not_found(self) -> None:
        """Test get_upstream_head when branch doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj13"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock empty output (branch not found)
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = ""

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_upstream_head(project_id)

                self.assertIsNone(result)

    def test_get_upstream_head_timeout(self) -> None:
        """Test get_upstream_head when query times out."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj14"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock timeout
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("git", 30),
                ):
                    result = get_upstream_head(project_id)

                self.assertIsNone(result)

    def test_get_upstream_head_custom_branch(self) -> None:
        """Test get_upstream_head with custom branch."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj15"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock successful git ls-remote for develop branch
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "fedcba987654321\trefs/heads/develop\n"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_upstream_head(project_id, branch="develop")

                self.assertIsNotNone(result)
                self.assertEqual(result["commit_hash"], "fedcba987654321")
                self.assertEqual(result["ref_name"], "refs/heads/develop")

    # Tests for get_gate_branch_head
    def test_get_gate_branch_head_success(self) -> None:
        """Test successful gate branch head query."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj16"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock git rev-parse
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "abc123def456789\n"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_gate_branch_head(project_id)

                self.assertEqual(result, "abc123def456789")

    def test_get_gate_branch_head_no_gate(self) -> None:
        """Test get_gate_branch_head when gate doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj17"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                result = get_gate_branch_head(project_id)
                self.assertIsNone(result)

    def test_get_gate_branch_head_branch_not_found(self) -> None:
        """Test get_gate_branch_head when branch doesn't exist in gate."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj18"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock failed git rev-parse
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 128
                mock_result.stderr = "fatal: ref does not exist"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = get_gate_branch_head(project_id, branch="nonexistent")

                self.assertIsNone(result)

    # Tests for compare_gate_vs_upstream
    def test_compare_gate_vs_upstream_in_sync(self) -> None:
        """Test compare when gate and upstream are in sync."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj19"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                commit_hash = "abc123def456789"

                # Mock get_gate_branch_head
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.get_gate_branch_head", return_value=commit_hash
                ):
                    # Mock get_upstream_head
                    with unittest.mock.patch(
                        "codexctl.lib.git_gate.get_upstream_head",
                        return_value={
                            "commit_hash": commit_hash,
                            "ref_name": "refs/heads/main",
                            "upstream_url": "https://example.com/repo.git",
                        },
                    ):
                        result = compare_gate_vs_upstream(project_id)

                self.assertEqual(result.branch, "main")
                self.assertEqual(result.gate_head, commit_hash)
                self.assertEqual(result.upstream_head, commit_hash)
                self.assertFalse(result.is_stale)
                self.assertEqual(result.commits_behind, 0)
                self.assertIsNone(result.error)

    def test_compare_gate_vs_upstream_stale(self) -> None:
        """Test compare when gate is stale."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj20"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                gate_hash = "old123"
                upstream_hash = "new456"

                # Mock get_gate_branch_head
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.get_gate_branch_head", return_value=gate_hash
                ):
                    # Mock get_upstream_head
                    with unittest.mock.patch(
                        "codexctl.lib.git_gate.get_upstream_head",
                        return_value={
                            "commit_hash": upstream_hash,
                            "ref_name": "refs/heads/main",
                            "upstream_url": "https://example.com/repo.git",
                        },
                    ):
                        # Mock _count_commits_behind
                        with unittest.mock.patch(
                            "codexctl.lib.git_gate._count_commits_behind", return_value=5
                        ):
                            result = compare_gate_vs_upstream(project_id)

                self.assertEqual(result.branch, "main")
                self.assertEqual(result.gate_head, gate_hash)
                self.assertEqual(result.upstream_head, upstream_hash)
                self.assertTrue(result.is_stale)
                self.assertEqual(result.commits_behind, 5)
                self.assertIsNone(result.error)

    def test_compare_gate_vs_upstream_gate_not_initialized(self) -> None:
        """Test compare when gate is not initialized."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj21"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                # Mock get_gate_branch_head to return None
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.get_gate_branch_head", return_value=None
                ):
                    result = compare_gate_vs_upstream(project_id)

                self.assertEqual(result.branch, "main")
                self.assertIsNone(result.gate_head)
                self.assertIsNone(result.upstream_head)
                self.assertFalse(result.is_stale)
                self.assertIsNone(result.commits_behind)
                self.assertEqual(result.error, "Gate not initialized")

    def test_compare_gate_vs_upstream_upstream_unreachable(self) -> None:
        """Test compare when upstream is unreachable."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj22"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                gate_hash = "abc123"

                # Mock get_gate_branch_head
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.get_gate_branch_head", return_value=gate_hash
                ):
                    # Mock get_upstream_head to return None
                    with unittest.mock.patch(
                        "codexctl.lib.git_gate.get_upstream_head", return_value=None
                    ):
                        result = compare_gate_vs_upstream(project_id)

                self.assertEqual(result.branch, "main")
                self.assertEqual(result.gate_head, gate_hash)
                self.assertIsNone(result.upstream_head)
                self.assertFalse(result.is_stale)
                self.assertIsNone(result.commits_behind)
                self.assertEqual(result.error, "Could not reach upstream")

    def test_compare_gate_vs_upstream_commits_behind_unavailable(self) -> None:
        """Test compare when commits behind cannot be determined."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj23"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                gate_hash = "old123"
                upstream_hash = "new456"

                # Mock get_gate_branch_head
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.get_gate_branch_head", return_value=gate_hash
                ):
                    # Mock get_upstream_head
                    with unittest.mock.patch(
                        "codexctl.lib.git_gate.get_upstream_head",
                        return_value={
                            "commit_hash": upstream_hash,
                            "ref_name": "refs/heads/main",
                            "upstream_url": "https://example.com/repo.git",
                        },
                    ):
                        # Mock _count_commits_behind to return None
                        with unittest.mock.patch(
                            "codexctl.lib.git_gate._count_commits_behind", return_value=None
                        ):
                            result = compare_gate_vs_upstream(project_id)

                self.assertTrue(result.is_stale)
                self.assertIsNone(result.commits_behind)

    # Tests for sync_gate_branches
    def test_sync_gate_branches_success(self) -> None:
        """Test successful sync of gate branches."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj24"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock successful git remote update
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "Fetching origin\n"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = sync_gate_branches(project_id)

                self.assertTrue(result["success"])
                self.assertEqual(result["updated_branches"], ["all"])
                self.assertEqual(result["errors"], [])

    def test_sync_gate_branches_gate_not_initialized(self) -> None:
        """Test sync when gate is not initialized."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj25"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                result = sync_gate_branches(project_id)

                self.assertFalse(result["success"])
                self.assertEqual(result["updated_branches"], [])
                self.assertEqual(result["errors"], ["Gate not initialized"])

    def test_sync_gate_branches_network_failure(self) -> None:
        """Test sync when network update fails."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj26"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock failed git remote update
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 1
                mock_result.stderr = "fatal: could not fetch origin"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = sync_gate_branches(project_id)

                self.assertFalse(result["success"])
                self.assertIn("remote update failed", result["errors"][0])

    def test_sync_gate_branches_timeout(self) -> None:
        """Test sync when operation times out."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj27"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock timeout
                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("git", 120),
                ):
                    result = sync_gate_branches(project_id)

                self.assertFalse(result["success"])
                self.assertEqual(result["errors"], ["Sync timed out"])

    def test_sync_gate_branches_specific_branches(self) -> None:
        """Test sync with specific branches."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj28"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
  default_branch: main
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock successful git remote update
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "Fetching origin\n"

                with unittest.mock.patch(
                    "codexctl.lib.git_gate.subprocess.run", return_value=mock_result
                ):
                    result = sync_gate_branches(project_id, branches=["main", "develop"])

                self.assertTrue(result["success"])
                self.assertEqual(result["updated_branches"], ["main", "develop"])
                self.assertEqual(result["errors"], [])

    # Tests for gate sharing validation
    def test_find_projects_sharing_gate(self) -> None:
        """Test finding projects that share a gate path."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            shared_gate = state_dir / "gate" / "shared.git"

            # Create two projects sharing the same gate
            write_project(
                config_root,
                "proj-a",
                f"""
project:
  id: proj-a
git:
  upstream_url: https://github.com/org/repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            write_project(
                config_root,
                "proj-b",
                f"""
project:
  id: proj-b
git:
  upstream_url: https://github.com/org/repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Find projects sharing the gate, excluding proj-a
                sharing = find_projects_sharing_gate(shared_gate, exclude_project="proj-a")

                self.assertEqual(len(sharing), 1)
                self.assertEqual(sharing[0][0], "proj-b")
                self.assertEqual(sharing[0][1], "https://github.com/org/repo.git")

    def test_validate_gate_upstream_match_same_url(self) -> None:
        """Test validation passes when projects share gate with same upstream."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            shared_gate = state_dir / "gate" / "shared.git"

            # Create two projects sharing the same gate AND same upstream
            write_project(
                config_root,
                "proj-same-a",
                f"""
project:
  id: proj-same-a
git:
  upstream_url: https://github.com/org/repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            write_project(
                config_root,
                "proj-same-b",
                f"""
project:
  id: proj-same-b
git:
  upstream_url: https://github.com/org/repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Should not raise - same upstream URL
                validate_gate_upstream_match("proj-same-a")
                validate_gate_upstream_match("proj-same-b")

    def test_validate_gate_upstream_match_different_url_fails(self) -> None:
        """Test validation fails when projects share gate with different upstreams."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            shared_gate = state_dir / "gate" / "conflict.git"

            # Create two projects sharing the same gate but DIFFERENT upstreams
            write_project(
                config_root,
                "proj-conflict-a",
                f"""
project:
  id: proj-conflict-a
git:
  upstream_url: https://github.com/org/repo-A.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            write_project(
                config_root,
                "proj-conflict-b",
                f"""
project:
  id: proj-conflict-b
git:
  upstream_url: https://github.com/org/repo-B.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Should raise SystemExit with helpful error message
                with self.assertRaises(SystemExit) as ctx:
                    validate_gate_upstream_match("proj-conflict-a")

                error_msg = str(ctx.exception)
                self.assertIn("Gate path conflict detected", error_msg)
                self.assertIn("proj-conflict-a", error_msg)
                self.assertIn("proj-conflict-b", error_msg)
                self.assertIn("repo-A.git", error_msg)
                self.assertIn("repo-B.git", error_msg)

    def test_init_project_gate_rejects_mismatched_upstream(self) -> None:
        """Test init_project_gate refuses when another project uses gate with different upstream."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            shared_gate = state_dir / "gate" / "init-conflict.git"

            # Create existing project with gate
            write_project(
                config_root,
                "existing-proj",
                f"""
project:
  id: existing-proj
git:
  upstream_url: https://github.com/org/existing-repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            # Create new project trying to use same gate with different upstream
            write_project(
                config_root,
                "new-proj",
                f"""
project:
  id: new-proj
git:
  upstream_url: https://github.com/org/different-repo.git
gate:
  path: {shared_gate}
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                with self.assertRaises(SystemExit) as ctx:
                    init_project_gate("new-proj")

                error_msg = str(ctx.exception)
                self.assertIn("Gate path conflict", error_msg)
                self.assertIn("existing-proj", error_msg)
