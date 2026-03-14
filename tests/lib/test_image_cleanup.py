# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

import subprocess
import unittest.mock

from terok.lib.containers.image_cleanup import (
    ImageInfo,
    cleanup_images,
    find_orphaned_images,
    list_images,
)


def _podman_result(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """Create a mock podman result."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestImageInfo:
    """Tests for ImageInfo dataclass."""

    def test_full_name_tagged(self) -> None:
        img = ImageInfo("terok-l0", "ubuntu-24.04", "sha256:abc", "500MB", "2 days ago")
        assert img.full_name == "terok-l0:ubuntu-24.04"

    def test_full_name_dangling(self) -> None:
        img = ImageInfo("<none>", "<none>", "sha256:abc123def456", "500MB", "2 days ago")
        assert img.full_name == "<none> (sha256:abc12)"


class TestListImages:
    """Tests for list_images()."""

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    def test_list_all_terok_images(self, mock_podman: unittest.mock.Mock) -> None:
        mock_podman.return_value = _podman_result(
            "terok-l0\tubuntu-24.04\tsha256:aaa\t500MB\t2 days ago\n"
            "terok-l1-cli\tubuntu-24.04\tsha256:bbb\t1.2GB\t2 days ago\n"
            "myproj\tl2-cli\tsha256:ccc\t1.5GB\t1 day ago\n"
            "ubuntu\t24.04\tsha256:ddd\t77MB\t3 weeks ago\n"
        )
        images = list_images()
        assert len(images) == 3
        names = [img.full_name for img in images]
        assert "terok-l0:ubuntu-24.04" in names
        assert "terok-l1-cli:ubuntu-24.04" in names
        assert "myproj:l2-cli" in names
        # Non-terok image should be excluded
        assert "ubuntu:24.04" not in names

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    def test_list_filtered_by_project(self, mock_podman: unittest.mock.Mock) -> None:
        mock_podman.return_value = _podman_result(
            "terok-l0\tubuntu-24.04\tsha256:aaa\t500MB\t2 days ago\n"
            "proj-a\tl2-cli\tsha256:bbb\t1.5GB\t1 day ago\n"
            "proj-b\tl2-cli\tsha256:ccc\t1.5GB\t1 day ago\n"
        )
        images = list_images("proj-a")
        names = [img.full_name for img in images]
        # L0/L1 always shown; only matching L2
        assert "terok-l0:ubuntu-24.04" in names
        assert "proj-a:l2-cli" in names
        assert "proj-b:l2-cli" not in names

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    def test_list_images_podman_failure(self, mock_podman: unittest.mock.Mock) -> None:
        mock_podman.return_value = _podman_result(returncode=1)
        assert list_images() == []

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    def test_l2_dev_and_web_tags(self, mock_podman: unittest.mock.Mock) -> None:
        mock_podman.return_value = _podman_result(
            "myproj\tl2-dev\tsha256:aaa\t1GB\t1 day ago\n"
            "myproj\tl2-web\tsha256:bbb\t1GB\t1 day ago\n"
        )
        images = list_images()
        assert len(images) == 2


class TestFindOrphanedImages:
    """Tests for find_orphaned_images()."""

    @unittest.mock.patch("terok.lib.containers.image_cleanup._is_terok_built_image")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._find_dangling_terok_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.list_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._known_project_ids")
    def test_finds_orphaned_l2(
        self,
        mock_known: unittest.mock.Mock,
        mock_list: unittest.mock.Mock,
        mock_dangling: unittest.mock.Mock,
        mock_built: unittest.mock.Mock,
    ) -> None:
        mock_known.return_value = {"proj-a"}
        mock_dangling.return_value = []
        mock_built.return_value = True
        mock_list.return_value = [
            ImageInfo("proj-a", "l2-cli", "sha256:aaa", "1GB", "1 day ago"),
            ImageInfo("proj-deleted", "l2-cli", "sha256:bbb", "1GB", "5 days ago"),
        ]
        orphaned = find_orphaned_images()
        assert len(orphaned) == 1
        assert orphaned[0].repository == "proj-deleted"

    @unittest.mock.patch("terok.lib.containers.image_cleanup._is_terok_built_image")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._find_dangling_terok_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.list_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._known_project_ids")
    def test_skips_non_terok_l2_images(
        self,
        mock_known: unittest.mock.Mock,
        mock_list: unittest.mock.Mock,
        mock_dangling: unittest.mock.Mock,
        mock_built: unittest.mock.Mock,
    ) -> None:
        """L2-tagged images not built by terok should not be treated as orphaned."""
        mock_known.return_value = set()
        mock_dangling.return_value = []
        mock_built.return_value = False  # not a terok-built image
        mock_list.return_value = [
            ImageInfo("foreign-img", "l2-cli", "sha256:fff", "1GB", "1 day ago"),
        ]
        orphaned = find_orphaned_images()
        assert len(orphaned) == 0

    @unittest.mock.patch("terok.lib.containers.image_cleanup._is_terok_built_image")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._find_dangling_terok_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.list_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._known_project_ids")
    def test_deduplicates_by_image_id(
        self,
        mock_known: unittest.mock.Mock,
        mock_list: unittest.mock.Mock,
        mock_dangling: unittest.mock.Mock,
        mock_built: unittest.mock.Mock,
    ) -> None:
        mock_known.return_value = set()
        mock_built.return_value = True
        img = ImageInfo("proj-x", "l2-cli", "sha256:same", "1GB", "1 day ago")
        mock_dangling.return_value = [img]
        mock_list.return_value = [img]
        orphaned = find_orphaned_images()
        assert len(orphaned) == 1

    @unittest.mock.patch("terok.lib.containers.image_cleanup._find_dangling_terok_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.list_images")
    @unittest.mock.patch("terok.lib.containers.image_cleanup._known_project_ids")
    def test_skips_l2_orphan_detection_on_discovery_failure(
        self,
        mock_known: unittest.mock.Mock,
        mock_list: unittest.mock.Mock,
        mock_dangling: unittest.mock.Mock,
    ) -> None:
        """When project discovery fails, L2 images must NOT be treated as orphaned."""
        mock_known.return_value = None  # discovery failed
        mock_dangling.return_value = []
        mock_list.return_value = [
            ImageInfo("proj-a", "l2-cli", "sha256:aaa", "1GB", "1 day ago"),
        ]
        orphaned = find_orphaned_images()
        # Should not consider proj-a orphaned since we couldn't verify projects
        assert len(orphaned) == 0
        # list_images should not even be called when discovery fails
        mock_list.assert_not_called()


class TestCleanupImages:
    """Tests for cleanup_images()."""

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.find_orphaned_images")
    def test_dry_run(
        self,
        mock_orphaned: unittest.mock.Mock,
        mock_podman: unittest.mock.Mock,
    ) -> None:
        mock_orphaned.return_value = [
            ImageInfo("old-proj", "l2-cli", "sha256:abc", "1GB", "5 days ago"),
        ]
        result = cleanup_images(dry_run=True)
        assert result.dry_run
        assert len(result.removed) == 1
        # Should NOT call podman rm in dry-run mode
        mock_podman.assert_not_called()

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.find_orphaned_images")
    def test_actual_cleanup(
        self,
        mock_orphaned: unittest.mock.Mock,
        mock_podman: unittest.mock.Mock,
    ) -> None:
        mock_orphaned.return_value = [
            ImageInfo("old-proj", "l2-cli", "sha256:abc", "1GB", "5 days ago"),
        ]
        mock_podman.return_value = _podman_result()
        result = cleanup_images(dry_run=False)
        assert not result.dry_run
        assert len(result.removed) == 1
        mock_podman.assert_called_once_with("image", "rm", "sha256:abc")

    @unittest.mock.patch("terok.lib.containers.image_cleanup._run_podman")
    @unittest.mock.patch("terok.lib.containers.image_cleanup.find_orphaned_images")
    def test_cleanup_failure(
        self,
        mock_orphaned: unittest.mock.Mock,
        mock_podman: unittest.mock.Mock,
    ) -> None:
        mock_orphaned.return_value = [
            ImageInfo("old-proj", "l2-cli", "sha256:abc", "1GB", "5 days ago"),
        ]
        mock_podman.return_value = _podman_result(returncode=1)
        result = cleanup_images(dry_run=False)
        assert len(result.removed) == 0
        assert len(result.failed) == 1

    @unittest.mock.patch("terok.lib.containers.image_cleanup.find_orphaned_images")
    def test_nothing_to_clean(self, mock_orphaned: unittest.mock.Mock) -> None:
        mock_orphaned.return_value = []
        result = cleanup_images()
        assert len(result.removed) == 0
        assert len(result.failed) == 0
