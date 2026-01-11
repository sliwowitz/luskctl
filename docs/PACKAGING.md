### Packaging luskctl for both pip (Python) and distro packages (deb/rpm)

This repository is set up to support two installation modes, both of which share the **same single source of truth** for templates and scripts:

1) Python packaging (pip / Poetry installs)
- Provides console scripts `luskctl` and `luskctl-tui`.
- Ships templates and helper scripts as package resources bundled inside the wheel (single source of truth under `src/luskctl/resources/`).
- Runtime loads these resources via `importlib.resources` and does not depend on external paths such as `/usr/share`.

2) Distribution packages (deb/rpm) following FHS for config/state/binaries
- Install configuration under `/etc/luskctl`.
- Install binaries as standard Python console entry points under `/usr/bin`.
- Writable state still lives under `/var/lib/luskctl` for system-wide installs (or the XDG data dir for user installs).

The code follows simple Linux/XDG conventions with small environment overrides. No complex prefix probing is used.

Key points implemented
- Single source of truth for runtime assets (templates and scripts) lives under the Python package: `src/luskctl/resources/{templates,scripts}`.
- Runtime loads assets exclusively via `importlib.resources` from the installed package; it does **not** read from `/usr/share/luskctl`.
- MANIFEST.in includes all resource assets for sdist builds; `pyproject.toml` includes them as package-data in wheels.

Recommended best practices (near-term)
- Use environment overrides when running from non-standard layouts:
  - `LUSKCTL_CONFIG_DIR` (points to a directory that contains `config.yml` and `projects/`)
  - `LUSKCTL_CONFIG_FILE` (points directly to a `config.yml`)
  - `LUSKCTL_STATE_DIR` (points to writable state root)
    - For distro packages you typically do not need any overrides; config lives in `/etc/luskctl`, binaries under `/usr/bin`, and user state goes to `${XDG_DATA_HOME:-~/.local/share}/luskctl`.

Current layout (implemented)
- `src/luskctl/resources/templates/` — Dockerfile templates used to generate images.
- `src/luskctl/resources/scripts/` — helper scripts staged into the build context and used by generated images.
- Access via `importlib.resources.files("luskctl") / "resources" / "templates"` (and `... / "scripts"`).

Debian/RPM packaging notes
- Use the Python build backend to produce artifacts:
  - `python -m build`  # produces sdist and wheel
- For Debian, `dh-sequence-python3` can use the sdist/wheel; install configuration and binaries to FHS targets:
  - `/etc/luskctl/**` (config.yml, projects/*/project.yml)
  - console scripts are auto-installed to `/usr/bin` by the distro tooling.
  - templates and scripts are consumed directly from the installed Python package resources (no `/usr/share/luskctl` mirror required).
- For RPM, use `%pyproject_buildrequires` / `%pyproject_wheel` / `%pyproject_install` macros. Map configuration files into `%{buildroot}%{_sysconfdir}/luskctl`. Runtime templates/scripts are read from the Python package.

pip --prefix on Debian/Ubuntu (posix_local scheme)
-----------------------------------------------

On Debian/Ubuntu, pip defaults to the "posix_local" installation scheme when installing outside of a virtualenv and without --user. This scheme appends a trailing "/local" segment under the given prefix. As a result, the effective installation targets are:

- Scripts:   {prefix}/local/bin
- Purelib:   {prefix}/local/lib/pythonX.Y/dist-packages (or site-packages depending on distro)

Implications for custom prefixes:

- If you want everything under /virt/podman/local, pass --prefix=/virt/podman (leave off the trailing /local) and let pip add "/local".
  - Correct:  python -m pip install --prefix=/virt/podman .
  - Result:   /virt/podman/local/bin/luskctl and /virt/podman/local/lib/pythonX.Y/dist-packages/luskctl

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
  1) `LUSKCTL_CONFIG_FILE` (explicit file)
  2) `${XDG_CONFIG_HOME:-~/.config}/luskctl/config.yml` (user override)
  3) `sys.prefix/etc/luskctl/config.yml` (pip/venv data-files)
  4) `/etc/luskctl/config.yml` (system default)
- Projects directory (system):
  1) `LUSKCTL_CONFIG_DIR/projects`
  2) `sys.prefix/etc/luskctl/projects` (pip/venv data-files)
  3) `/etc/luskctl/projects`
- Projects directory (user):
  - `${XDG_CONFIG_HOME:-~/.config}/luskctl/projects`
- Shared data (templates/scripts):
  - Loaded from Python package resources bundled with the wheel/install (single source of truth under `luskctl/resources/{templates,scripts}`).
- Writable state (tasks/cache/build):
  1) `LUSKCTL_STATE_DIR`
  2) `${XDG_DATA_HOME:-~/.local/share}/luskctl`

Build directory
---------------

- Generated artifacts default to the "build" directory under the writable state root, e.g. ${state_root}/build/<project>/L0.Dockerfile.

FHS note about writability
--------------------------

- Writable data belongs under `/var/lib/luskctl` for system installs or under `${XDG_DATA_HOME:-~/.local/share}/luskctl` for users.
- The application never writes under `/usr/share` and does not read templates/scripts from there; instead it always uses its packaged resources.

Developer workflow
- For source checkouts, you can run `luskctl config` to see which package resources are available.
- You can override writable locations with:
  - `LUSKCTL_CONFIG_DIR` (system config root with projects/)
  - `LUSKCTL_STATE_DIR` (state root used for build dir)
  - User overrides live in `${XDG_CONFIG_HOME:-~/.config}/luskctl`.

Notes
- The application does not attempt to read from `/usr/share/luskctl` at runtime; it always uses its packaged resources to avoid ambiguity.
