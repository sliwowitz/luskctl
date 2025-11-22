### Packaging codexctl for both pip (Python) and FHS (deb/rpm)

This repository is set up to support two installation modes:

1) Python packaging (pip install codexctl)
- Provides console scripts `codexctl` and `codexctl-tui`.
- Ships templates and helper scripts as package resources bundled inside the wheel (single source of truth under `src/codexctl/resources/`).
- Runtime loads these resources via `importlib.resources` and does not depend on external paths.

2) Distribution packages (deb/rpm) following FHS
- Install configuration under /etc/codexctl and mirror shared assets under /usr/share/codexctl.
- Binaries are standard Python console entry points placed under /usr/bin.

The code follows simple Linux/XDG conventions with small environment overrides. No complex prefix probing is used.

Key points implemented
- Single source of truth for runtime assets (templates and scripts) lives under the Python package: `src/codexctl/resources/{templates,scripts}`.
- Runtime loads assets exclusively via `importlib.resources` from the installed package; no external probing.
- For distro/FHS packages, the same assets are mirrored to `/usr/share/codexctl/{templates,scripts}` at install time for host tools that expect files on disk.
- MANIFEST.in includes all resource assets for sdist builds; pyproject includes them as package-data in wheels.

Recommended best practices (near-term)
- Use environment overrides when running from non-standard layouts:
  - CODEXCTL_CONFIG_DIR (points to a directory that contains config.yml and projects/)
  - CODEXCTL_CONFIG_FILE (points directly to a config.yml)
  - CODEXCTL_STATE_DIR (points to writable state root)
    - For distro packages you typically do not need any overrides; files live in /etc and /usr/share and user state goes to ${XDG_DATA_HOME:-~/.local/share}/codexctl.

Current layout (implemented)
- `src/codexctl/resources/templates/` — Dockerfile templates used to generate images.
- `src/codexctl/resources/scripts/` — helper scripts staged into the build context and used by generated images.
- Access via `importlib.resources.files("codexctl") / "resources" / "templates"` (and `... / "scripts"`).

Debian/RPM packaging notes
- Use the Python build backend to produce artifacts:
  - python -m build  # produces sdist and wheel
- For Debian, dh-sequence-python3 can use the sdist/wheel; install data files to FHS targets (as mirrors):
  - /etc/codexctl/** (config.yml, projects/*/project.yml)
  - /usr/share/codexctl/templates/**
  - /usr/share/codexctl/scripts/**
  - console scripts are auto-installed to /usr/bin by the distro tooling.
  - For RPM, use %pyproject_buildrequires / %pyproject_wheel / %pyproject_install macros. Map data files into %{buildroot}%{_sysconfdir}/codexctl and %{buildroot}%{_datadir}/codexctl.

pip --prefix on Debian/Ubuntu (posix_local scheme)
-----------------------------------------------

On Debian/Ubuntu, pip defaults to the "posix_local" installation scheme when installing outside of a virtualenv and without --user. This scheme appends a trailing "/local" segment under the given prefix. As a result, the effective installation targets are:

- Scripts:   {prefix}/local/bin
- Purelib:   {prefix}/local/lib/pythonX.Y/dist-packages (or site-packages depending on distro)

Implications for custom prefixes:

- If you want everything under /virt/podman/local, pass --prefix=/virt/podman (leave off the trailing /local) and let pip add "/local".
  - Correct:  python -m pip install --prefix=/virt/podman .
  - Result:   /virt/podman/local/bin/codexctl and /virt/podman/local/lib/pythonX.Y/dist-packages/codexctl

- Do NOT include "/local" in the prefix yourself, otherwise you will get a nested path like /virt/podman/local/local/...
  - Wrong:    python -m pip install --prefix=/virt/podman/local .
  - Result:   /virt/podman/local/local/bin, /virt/podman/local/local/lib/pythonX.Y/...

Optional TUI extra and system packages

- The Textual TUI is an optional extra to avoid forcing upgrades to distro-managed packages like Pygments on Debian/Ubuntu.
- Base install (no TUI):
  - python -m pip install --prefix=/virt/podman .
- With TUI:
  - python -m pip install --prefix=/virt/podman '.[tui]'
- If you prefer a venv to avoid system scheme quirks:
  - python -m venv .venv && . .venv/bin/activate && pip install '.[tui]'

Runtime lookup strategy
- Config (read-only defaults):
  1) CODEXCTL_CONFIG_FILE (explicit file)
  2) ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml (user override)
  3) sys.prefix/etc/codexctl/config.yml (pip/venv data-files)
  4) /etc/codexctl/config.yml (system default)
- Projects directory (system):
  1) CODEXCTL_CONFIG_DIR/projects
  2) sys.prefix/etc/codexctl/projects (pip/venv data-files)
  3) /etc/codexctl/projects
- Projects directory (user):
  - ${XDG_CONFIG_HOME:-~/.config}/codexctl/projects
- Shared data (templates/scripts):
  - Loaded from Python package resources bundled with the wheel/install (single source of truth).
  - For system packages, identical copies are installed under `/usr/share/codexctl/{templates,scripts}` for host tools that are not Python-aware.
- Writable state (tasks/cache/build):
  1) CODEXCTL_STATE_DIR
  2) ${XDG_DATA_HOME:-~/.local/share}/codexctl

Build directory
---------------

- Generated artifacts default to the "build" directory under the writable state root, e.g. ${state_root}/build/<project>/L1.Dockerfile.

FHS note about writability
--------------------------

- `/usr/share/codexctl` ("share") must be treated as read-only. Templates/scripts are provided via Python package resources; `/usr/share/codexctl` is a mirror for distro packages.
- Writable data belongs under /var/lib/codexctl for system installs or under ${XDG_DATA_HOME:-~/.local/share}/codexctl for users. The application never writes under /usr/share.

Developer workflow
- For source checkouts, you can run `codexctl config` to see which package resources are available.
- You can override writable locations with:
  - `CODEXCTL_CONFIG_DIR` (system config root with projects/)
  - `CODEXCTL_STATE_DIR` (state root used for build dir)
  - User overrides live in `${XDG_CONFIG_HOME:-~/.config}/codexctl`.

Notes
- The application does not attempt to read from `/usr/share/codexctl` at runtime; it always uses its packaged resources to avoid ambiguity. System packages may still install mirrors under `/usr/share/codexctl` for non-Python consumers.
