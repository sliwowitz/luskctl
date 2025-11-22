### Packaging codexctl for both pip (Python) and FHS (deb/rpm)

This repository is set up to support two installation modes:

1) Python packaging (pip install codexctl)
- Provides console scripts `codexctl` and `codexctl-tui`.
- Ships configuration/templates as data files alongside the Python install prefix.
- Default search paths are resolved from the Python `sys.prefix` unless overridden by environment.

2) Distribution packages (deb/rpm) following FHS
- Install configuration under /etc/codexctl and shared assets under /usr/share/codexctl.
- Binaries are standard Python console entry points placed under /usr/bin.

The code follows simple Linux/XDG conventions with small environment overrides. No complex prefix probing is used.

Key points implemented
- pyproject.toml uses setuptools to publish the current modules from bin/ as py_modules and to install data-files under etc/codexctl and share/codexctl.
- Path lookup is intentionally simple and conventional (see below).
- MANIFEST.in includes all non-code assets for sdist builds.

Recommended best practices (near-term)
- Use environment overrides when running from non-standard layouts:
  - CODEXCTL_CONFIG_DIR (points to a directory that contains config.yml and projects/)
  - CODEXCTL_CONFIG_FILE (points directly to a config.yml)
  - CODEXCTL_STATE_DIR (points to writable state root)
    - For distro packages you typically do not need any overrides; files live in /etc and /usr/share and user state goes to ${XDG_DATA_HOME:-~/.local/share}/codexctl.

Recommended refactor (future improvement)
- Migrate to a src/ layout and a proper package (e.g., src/codexctl/__init__.py, src/codexctl/cli.py, src/codexctl/lib.py):
  - Pros: avoids accidental imports from CWD, works better with editable installs.
  - Example entry points: `codexctl = "codexctl.cli:main"`.
- Use importlib.resources to ship templates/scripts within the Python package instead of external data-files. This makes wheels self-contained and platform-agnostic:
  - Place assets under src/codexctl/data/templates and src/codexctl/data/scripts.
  - Access via `importlib.resources.files("codexctl.data").joinpath("templates")`.
  - For distro packaging, you can still install copies under /usr/share/codexctl if desired, but default to package resources for pip installs.
- Consider platformdirs for user configuration paths instead of hand-rolling XDG handling.

Debian/RPM packaging notes
- Use the Python build backend to produce artifacts:
  - python -m build  # produces sdist and wheel
- For Debian, dh-sequence-python3 can use the sdist/wheel; install data files to FHS targets:
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
  - Loaded from Python package resources bundled with the wheel/install.
- Writable state (tasks/cache/build):
  1) CODEXCTL_STATE_DIR
  2) ${XDG_DATA_HOME:-~/.local/share}/codexctl

Build directory
---------------

- Generated artifacts default to the "build" directory under the writable state root, e.g. ${state_root}/build/<project>/L1.Dockerfile.

FHS note about writability
--------------------------

- /usr/share/codexctl ("share") must be treated as read-only. Templates are provided via Python package resources or optionally mirrored in /usr/share for distro packages.
- Writable data belongs under /var/lib/codexctl for system installs or under ${XDG_DATA_HOME:-~/.local/share}/codexctl for users. The application never writes under /usr/share.

Developer workflow
- For source checkouts, prefer env vars for convenience:
  - CODEXCTL_CONFIG_DIR=$PWD/etc/codexctl
  - CODEXCTL_STATE_DIR=$PWD/var/lib/codexctl (or leave to use ${XDG_DATA_HOME:-~/.local/share}/codexctl)
  - Optionally place user project overrides under ~/.config/codexctl/projects

Migration checklist (if moving to src/ package)
- [ ] Create src/codexctl package; move bin/*.py into codexctl/ (split CLI/lib modules).
- [ ] Replace direct filesystem references with importlib.resources for bundled templates/scripts.
- [ ] Keep FHS installs by optionally copying resources to /usr/share in distro packages, while defaulting to package resources in pip installs.
- [ ] Add tests to exercise get_prefix/data resolution under env override, sys.prefix wheel, and FHS-ish setups.
