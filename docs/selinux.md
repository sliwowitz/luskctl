# SELinux & the socket transport

> [!WARNING]
> This documentation was written by an AI agent and might be inaccurate.

Since 0.7.3, terok defaults to **`services.mode: socket`** — Unix-socket
IPC between the per-container host services (gate, vault, SSH signer)
and task containers.  No TCP ports are claimed for terok's own services.

This page explains what that means on your distro, and how to opt out.

## What changes per distro

### Non-SELinux distros (Ubuntu, Debian, Arch, Alpine, …)

Nothing extra.  The per-container supervisor services bind Unix sockets,
containers mount them with `:z`, and everything works.  You will never
see a SELinux block in the setup output and you never need `sudo`.

### SELinux distros in permissive mode

Same as above.  Sockets bind normally, the default container-SELinux
policy covers the flow, `terok setup` skips the SELinux block.

### SELinux distros in enforcing mode (Fedora, RHEL, …)

By default SELinux blocks `container_t → unconfined_t` `connectto` on
Unix sockets (see [Dan Walsh][1] / [Podman #23972][2]).  To let rootless
Podman containers reach terok's host-side sockets, we ship a narrowly
targeted policy module (`terok_socket`, defining the `terok_socket_t`
socket type) that carves out this single exception.  Installing it is a one-time `sudo` operation per host.

`terok setup` on an enforcing host reports the policy stage as MISSING
and ends with an "SELinux policy required" hint that gives both fixes:
install the policy with `terok setup selinux` — it shows the exact
`sudo` command and, on request, the policy rules before anything runs —
or opt out by adding `services: {mode: tcp}` to
`~/.config/terok/config.yml`.  `terok sickbay` reports the same
condition as a warning.

The installer script is short, auditable, and sits next to the `.te`
policy source in the terok-sandbox package.  `terok setup selinux`
prints its exact path in the `sudo` command before anything runs (and
`--show` prints the compiled rules), so you can `cat` it first.
It compiles `terok_socket.te` with `checkmodule` / `semodule_package`
and loads it with `semodule -i`.

After running it, `terok setup` reports the policy as installed and task
containers can connect to the gate / vault / SSH-signer sockets.

#### Removing the policy

```bash
sudo semodule -r terok_socket
```

## Opting out: the TCP transport

If you can't or don't want to install the policy — shared host where
you don't have root, locked-down distro image, container build where
`sudo` isn't practical — set:

```yaml
# ~/.config/terok/config.yml
services:
  mode: tcp
```

This falls back to the TCP-loopback transport.  Each container launch
allocates three kernel-assigned loopback ports (vault broker, SSH
signer, gate); containers reach them via `host.containers.internal`.
Works on any distro, SELinux or not, zero extra setup.

The same section works per project — in a project's `project.yml` it
overrides the global choice for that project's tasks only (each
container gets its own supervisor, so mixed modes coexist on one
host).  A project pinning `services: {mode: socket}` still needs the
policy even after a global switch to `tcp`.

The TCP transport is **not** deprecated — it's a supported opt-out.
Caveat: the per-container ports are visible on the host via `ss -tlnp`
(127.0.0.1 only).  They don't leak off-loopback, but on multi-user
hosts another user could see that *something* is listening.

## Background

The socket story is an intermediate step toward a longer-term **bridge
mode** where task containers and terok service containers sit on a
shared rootless Podman bridge — container↔container connections don't
cross the SELinux host boundary, automatic MCS categories provide
per-task isolation, and no custom policy module is needed at all.
Bridge mode is tracked separately and depends on
[terok-shield](https://github.com/terok-ai/terok-shield) support.

[1]: https://danwalsh.livejournal.com/78643.html
[2]: https://github.com/containers/podman/discussions/23972
