"""Tests for headless provider registry and dispatch functions."""

import unittest
import unittest.mock
from dataclasses import FrozenInstanceError

from luskctl.lib.containers.headless_providers import (
    HEADLESS_PROVIDERS,
    PROVIDER_NAMES,
    build_headless_command,
    generate_agent_wrapper,
    get_provider,
)
from luskctl.lib.core.project_model import Project


def _make_project(**kwargs: object) -> Project:
    """Create a minimal Project with sensible defaults."""
    from pathlib import Path

    defaults: dict = {
        "id": "testproj",
        "security_class": "online",
        "upstream_url": None,
        "default_branch": "main",
        "root": Path("/tmp/test"),
        "tasks_root": Path("/tmp/test/tasks"),
        "gate_path": Path("/tmp/test/gate"),
        "staging_root": None,
        "ssh_key_name": None,
        "ssh_host_dir": None,
        "default_agent": None,
        "human_name": "Test User",
        "human_email": "test@example.com",
    }
    defaults.update(kwargs)
    return Project(**defaults)


class HeadlessProviderRegistryTests(unittest.TestCase):
    """Tests for the HEADLESS_PROVIDERS registry."""

    def test_all_six_providers_exist(self) -> None:
        """Registry contains exactly the six expected providers."""
        expected = {"claude", "codex", "copilot", "vibe", "blablador", "opencode"}
        self.assertEqual(set(HEADLESS_PROVIDERS.keys()), expected)

    def test_provider_names_tuple(self) -> None:
        """PROVIDER_NAMES is a tuple matching registry keys."""
        self.assertIsInstance(PROVIDER_NAMES, tuple)
        self.assertEqual(set(PROVIDER_NAMES), set(HEADLESS_PROVIDERS.keys()))

    def test_providers_are_frozen(self) -> None:
        """HeadlessProvider instances are immutable."""
        provider = HEADLESS_PROVIDERS["claude"]
        with self.assertRaises(FrozenInstanceError):
            provider.name = "changed"  # type: ignore[misc]

    def test_claude_provider_attributes(self) -> None:
        """Claude provider has expected attributes."""
        p = HEADLESS_PROVIDERS["claude"]
        self.assertEqual(p.name, "claude")
        self.assertEqual(p.binary, "claude")
        self.assertEqual(p.prompt_flag, "-p")
        self.assertTrue(p.supports_agents_json)
        self.assertTrue(p.supports_session_hook)
        self.assertTrue(p.supports_add_dir)
        self.assertTrue(p.supports_session_resume)
        self.assertEqual(p.log_format, "claude-stream-json")

    def test_codex_provider_attributes(self) -> None:
        """Codex provider has expected attributes."""
        p = HEADLESS_PROVIDERS["codex"]
        self.assertEqual(p.binary, "codex")
        self.assertEqual(p.headless_subcommand, "exec")
        self.assertEqual(p.prompt_flag, "")
        self.assertFalse(p.supports_agents_json)
        self.assertFalse(p.supports_session_resume)

    def test_copilot_provider_attributes(self) -> None:
        """Copilot provider has expected attributes."""
        p = HEADLESS_PROVIDERS["copilot"]
        self.assertEqual(p.binary, "copilot")
        self.assertEqual(p.prompt_flag, "-p")
        self.assertEqual(p.auto_approve_flags, ("--allow-all-tools",))

    def test_vibe_provider_attributes(self) -> None:
        """Vibe provider has expected attributes."""
        p = HEADLESS_PROVIDERS["vibe"]
        self.assertEqual(p.binary, "vibe")
        self.assertEqual(p.model_flag, "--agent")
        self.assertTrue(p.supports_session_resume)

    def test_blablador_provider_attributes(self) -> None:
        """Blablador provider has expected attributes."""
        p = HEADLESS_PROVIDERS["blablador"]
        self.assertEqual(p.binary, "blablador")
        self.assertIsNone(p.model_flag)
        self.assertEqual(p.continue_flag, "--continue")

    def test_opencode_provider_attributes(self) -> None:
        """OpenCode provider has expected attributes."""
        p = HEADLESS_PROVIDERS["opencode"]
        self.assertEqual(p.binary, "opencode")
        self.assertEqual(p.headless_subcommand, "run")
        self.assertEqual(p.resume_flag, "--session")


class GetProviderTests(unittest.TestCase):
    """Tests for get_provider() resolution."""

    def test_explicit_name(self) -> None:
        """Explicit provider name resolves correctly."""
        project = _make_project()
        p = get_provider("codex", project)
        self.assertEqual(p.name, "codex")

    def test_none_falls_back_to_project_default(self) -> None:
        """None name uses project.default_agent."""
        project = _make_project(default_agent="copilot")
        p = get_provider(None, project)
        self.assertEqual(p.name, "copilot")

    def test_none_falls_back_to_claude(self) -> None:
        """None name with no project default resolves to claude."""
        project = _make_project(default_agent=None)
        p = get_provider(None, project)
        self.assertEqual(p.name, "claude")

    def test_invalid_name_raises_system_exit(self) -> None:
        """Unknown provider name raises SystemExit."""
        project = _make_project()
        with self.assertRaises(SystemExit) as ctx:
            get_provider("nonexistent", project)
        self.assertIn("nonexistent", str(ctx.exception))


class BuildHeadlessCommandTests(unittest.TestCase):
    """Tests for build_headless_command() per provider."""

    def test_claude_command_uses_wrapper(self) -> None:
        """Claude command uses the wrapper function with --luskctl-timeout."""
        p = HEADLESS_PROVIDERS["claude"]
        cmd = build_headless_command(p, timeout=1800)
        self.assertIn("claude --luskctl-timeout 1800", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("--output-format stream-json", cmd)
        self.assertIn("--verbose", cmd)
        self.assertIn("prompt.txt", cmd)

    def test_claude_command_with_model_and_turns(self) -> None:
        """Claude command includes model and max-turns flags."""
        p = HEADLESS_PROVIDERS["claude"]
        cmd = build_headless_command(p, timeout=1800, model="opus", max_turns=50)
        self.assertIn("--model opus", cmd)
        self.assertIn("--max-turns 50", cmd)

    def test_codex_command(self) -> None:
        """Codex command uses exec subcommand and --full-auto."""
        p = HEADLESS_PROVIDERS["codex"]
        cmd = build_headless_command(p, timeout=1800)
        self.assertIn("codex exec", cmd)
        self.assertIn("--full-auto", cmd)
        self.assertIn("timeout 1800", cmd)
        self.assertIn("prompt.txt", cmd)

    def test_codex_command_with_model(self) -> None:
        """Codex command includes --model flag."""
        p = HEADLESS_PROVIDERS["codex"]
        cmd = build_headless_command(p, timeout=1800, model="o3")
        self.assertIn("--model o3", cmd)

    def test_copilot_command(self) -> None:
        """Copilot command uses -p flag and --allow-all-tools."""
        p = HEADLESS_PROVIDERS["copilot"]
        cmd = build_headless_command(p, timeout=900)
        self.assertIn("copilot", cmd)
        self.assertIn("--allow-all-tools", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("timeout 900", cmd)

    def test_vibe_command(self) -> None:
        """Vibe command uses --prompt flag."""
        p = HEADLESS_PROVIDERS["vibe"]
        cmd = build_headless_command(p, timeout=1800)
        self.assertIn("vibe", cmd)
        self.assertIn("--prompt", cmd)
        self.assertIn("prompt.txt", cmd)

    def test_vibe_command_with_model(self) -> None:
        """Vibe command uses --agent for model selection."""
        p = HEADLESS_PROVIDERS["vibe"]
        cmd = build_headless_command(p, timeout=1800, model="large")
        self.assertIn("--agent large", cmd)

    def test_opencode_command(self) -> None:
        """OpenCode command uses run subcommand."""
        p = HEADLESS_PROVIDERS["opencode"]
        cmd = build_headless_command(p, timeout=1800)
        self.assertIn("opencode run", cmd)
        self.assertIn("prompt.txt", cmd)

    def test_blablador_command(self) -> None:
        """Blablador command uses blablador binary."""
        p = HEADLESS_PROVIDERS["blablador"]
        cmd = build_headless_command(p, timeout=1800)
        self.assertIn("blablador", cmd)
        self.assertIn("prompt.txt", cmd)

    def test_all_commands_start_with_init(self) -> None:
        """All provider commands start with init-ssh-and-repo.sh."""
        for name, p in HEADLESS_PROVIDERS.items():
            cmd = build_headless_command(p, timeout=1800)
            self.assertTrue(cmd.startswith("init-ssh-and-repo.sh"), f"{name} missing init")


class GenerateAgentWrapperTests(unittest.TestCase):
    """Tests for generate_agent_wrapper() per provider."""

    @staticmethod
    def _claude_wrapper_fn(has_agents: bool, project: object, skip_permissions: bool) -> str:
        """Stub for agents._generate_claude_wrapper used in tests."""
        from luskctl.lib.containers.agents import _generate_claude_wrapper

        return _generate_claude_wrapper(has_agents, project, skip_permissions)

    def test_claude_wrapper_uses_claude_function(self) -> None:
        """Claude wrapper defines a claude() function with --add-dir."""
        project = _make_project()
        p = HEADLESS_PROVIDERS["claude"]
        wrapper = generate_agent_wrapper(
            p, project, has_agents=False, claude_wrapper_fn=self._claude_wrapper_fn
        )
        self.assertIn("claude()", wrapper)
        self.assertIn("--add-dir", wrapper)
        self.assertIn("GIT_AUTHOR_NAME=Claude", wrapper)

    def test_claude_wrapper_with_agents(self) -> None:
        """Claude wrapper includes agents.json loading when has_agents=True."""
        project = _make_project()
        p = HEADLESS_PROVIDERS["claude"]
        wrapper = generate_agent_wrapper(
            p, project, has_agents=True, claude_wrapper_fn=self._claude_wrapper_fn
        )
        self.assertIn("agents.json", wrapper)

    def test_claude_wrapper_requires_fn(self) -> None:
        """Claude provider without claude_wrapper_fn raises ValueError."""
        project = _make_project()
        p = HEADLESS_PROVIDERS["claude"]
        with self.assertRaises(ValueError):
            generate_agent_wrapper(p, project, has_agents=False)

    def test_codex_wrapper(self) -> None:
        """Codex wrapper defines a codex() function with git env vars."""
        project = _make_project()
        p = HEADLESS_PROVIDERS["codex"]
        wrapper = generate_agent_wrapper(p, project, has_agents=False)
        self.assertIn("codex()", wrapper)
        self.assertIn("GIT_AUTHOR_NAME=Codex", wrapper)
        self.assertIn("GIT_AUTHOR_EMAIL=noreply@openai.com", wrapper)
        self.assertNotIn("--add-dir", wrapper)

    def test_generic_wrapper_has_timeout_support(self) -> None:
        """All non-Claude wrappers support --luskctl-timeout."""
        project = _make_project()
        for name, p in HEADLESS_PROVIDERS.items():
            if name == "claude":
                continue
            wrapper = generate_agent_wrapper(p, project, has_agents=False)
            self.assertIn("--luskctl-timeout", wrapper, f"{name} missing timeout support")

    def test_generic_wrapper_has_git_committer(self) -> None:
        """All wrappers set GIT_COMMITTER_NAME from project human_name."""
        project = _make_project(human_name="Alice", human_email="alice@example.com")
        for name, p in HEADLESS_PROVIDERS.items():
            kwargs: dict = {}
            if name == "claude":
                kwargs["claude_wrapper_fn"] = self._claude_wrapper_fn
            wrapper = generate_agent_wrapper(p, project, has_agents=False, **kwargs)
            self.assertIn("Alice", wrapper, f"{name} missing committer name")

    def test_opencode_wrapper_has_continue_flag(self) -> None:
        """OpenCode wrapper includes --continue session resume support."""
        project = _make_project()
        p = HEADLESS_PROVIDERS["opencode"]
        wrapper = generate_agent_wrapper(p, project, has_agents=False)
        self.assertIn("--continue", wrapper)
        self.assertIn("session-id.txt", wrapper)
