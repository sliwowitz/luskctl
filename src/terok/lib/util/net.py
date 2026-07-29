# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Small URL helpers — host formatting, authority normalisation."""

from __future__ import annotations

from urllib.parse import urlsplit


def git_remote_host(url: str) -> str | None:
    """The host a git remote points at, or ``None`` when it names a local path.

    Covers both forms git accepts: scheme URLs (``https://``, ``ssh://``),
    and the scp-like ``git@github.com:org/repo`` shorthand — which carries no
    scheme, so ``urlsplit`` reads it hostless and would silently drop the
    host.  The result is lower-cased, since every caller compares it.
    """
    if "://" in url:
        return urlsplit(url).hostname or None
    head, sep, _path = url.partition(":")
    if not sep or "/" in head:
        return None  # no colon, or a path-like prefix — a local repo, not a remote
    return head.rpartition("@")[2].lower() or None


def url_host(host: str) -> str:
    """*host* formatted for an HTTP URL authority.

    IPv6 literals are wrapped in square brackets so ``::1`` becomes
    ``[::1]``; IPv4 addresses and hostnames pass through unchanged.
    Already-bracketed input is left alone to avoid double-wrapping.
    """
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
