### Packaging terok for both pip (Python) and distro packages (deb/rpm)

This repository is set up to support two installation modes, both of which share the **same single source of truth** for templates and scripts:

1) Python packaging (pip / Poetry installs)
- Provides console scripts `terok` and `terok`.
- Ships templates and helper scripts as package resources bundled inside the wheel (single source of truth under `src/terok/resources/`).
- Runtime loads these resources via `importlib.resources` and does not depend on external paths such as `/usr/share`.

2) Distribution packages (deb/rpm) following FHS for config/state/binaries
- Install configuration under `/etc/terok`.
- Install binaries as standard Python console entry points under `/usr/bin`.
- Writable state still lives under `/var/lib/terok` for system-wide installs (or the XDG data dir for user installs).

The code follows simple Linux/XDG conventions with small environment overrides. No complex prefix probing is used.

Key points implemented
- Single source of truth for runtime assets (templates and scripts) lives under the Python package: `src/terok/resources/{templates,scripts}`.
- Runtime loads assets exclusively via `importlib.resources` from the installed package; it does **not** read from `/usr/share/terok`.
- MANIFEST.in includes all resource assets for sdist builds; `pyproject.toml` includes them as package-data in wheels.

Recommended best practices (near-term)
- Use environment overrides when running from non-standard layouts:
  - `TEROK_CONFIG_DIR` (points to a directory that contains `config.yml` and `projects/`)
  - `TEROK_CONFIG_FILE` (points directly to a `config.yml`)
  - `TEROK_STATE_DIR` (points to writable state root)
    - For distro packages you typically do not need any overrides; config lives in `/etc/terok`, binaries under `/usr/bin`, and user state goes to `${XDG_DATA_HOME:-~/.local/share}/terok`.

Current layout (implemented)
- `src/terok/resources/templates/` — Dockerfile templates used to generate images.
- `src/terok/resources/scripts/` — helper scripts staged into the build context and used by generated images.
- Access via `importlib.resources.files("terok") / "resources" / "templates"` (and `... / "scripts"`).

Debian/RPM packaging notes
- Use the Python build backend to produce artifacts:
  - `python -m build`  # produces sdist and wheel
- For Debian, `dh-sequence-python3` can use the sdist/wheel; install configuration and binaries to FHS targets:
  - `/etc/terok/**` (config.yml, projects/*/project.yml)
  - console scripts are auto-installed to `/usr/bin` by the distro tooling.
  - templates and scripts are consumed directly from the installed Python package resources (no `/usr/share/terok` mirror required).
- For RPM, use `%pyproject_buildrequires` / `%pyproject_wheel` / `%pyproject_install` macros. Map configuration files into `%{buildroot}%{_sysconfdir}/terok`. Runtime templates/scripts are read from the Python package.

pip --prefix on Debian/Ubuntu (posix_local scheme)
-----------------------------------------------

On Debian/Ubuntu, pip defaults to the "posix_local" installation scheme when installing outside of a virtualenv and without --user. This scheme appends a trailing "/local" segment under the given prefix. As a result, the effective installation targets are:

- Scripts:   {prefix}/local/bin
- Purelib:   {prefix}/local/lib/pythonX.Y/dist-packages (or site-packages depending on distro)

Implications for custom prefixes:

- If you want everything under /virt/podman/local, pass --prefix=/virt/podman (leave off the trailing /local) and let pip add "/local".
  - Correct:  python -m pip install --prefix=/virt/podman .
  - Result:   /virt/podman/local/bin/terok and /virt/podman/local/lib/pythonX.Y/dist-packages/terok

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
  1) `TEROK_CONFIG_FILE` (explicit file)
  2) `${XDG_CONFIG_HOME:-~/.config}/terok/config.yml` (user override)
  3) `sys.prefix/etc/terok/config.yml` (pip/venv data-files)
  4) `/etc/terok/config.yml` (system default)
- Projects directory (system):
  1) `TEROK_CONFIG_DIR/projects`
  2) `sys.prefix/etc/terok/projects` (pip/venv data-files)
  3) `/etc/terok/projects`
- Projects directory (user):
  - `${XDG_CONFIG_HOME:-~/.config}/terok/projects`
- Shared data (templates/scripts):
  - Loaded from Python package resources bundled with the wheel/install (single source of truth under `terok/resources/{templates,scripts}`).
- Writable state (tasks/cache/build):
  1) `TEROK_STATE_DIR`
  2) `${XDG_DATA_HOME:-~/.local/share}/terok`

Build directory
---------------

- Generated artifacts default to the "build" directory under the writable state root, e.g. ${state_root}/build/<project>/L0.Dockerfile.

FHS note about writability
--------------------------

- Writable data belongs under `/var/lib/terok` for system installs or under `${XDG_DATA_HOME:-~/.local/share}/terok` for users.
- The application never writes under `/usr/share` and does not read templates/scripts from there; instead it always uses its packaged resources.

Developer workflow
- For source checkouts, you can run `terokctl config` to see which package resources are available.
- You can override writable locations with:
  - `TEROK_CONFIG_DIR` (system config root with projects/)
  - `TEROK_STATE_DIR` (state root used for build dir)
  - User overrides live in `${XDG_CONFIG_HOME:-~/.config}/terok`.

Notes
- The application does not attempt to read from `/usr/share/terok` at runtime; it always uses its packaged resources to avoid ambiguity.
