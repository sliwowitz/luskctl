# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""CLI command modules.

Each module exposes ``register(subparsers)`` to add its argument parsers
and ``dispatch(args) -> bool`` to handle parsed arguments.  The dispatch
function returns ``True`` if it handled the command, ``False`` otherwise.
"""
