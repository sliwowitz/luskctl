# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Copy shared Mermaid zoom JS into the docs build."""

import mkdocs_gen_files
from mkdocs_terok import mermaid_zoom_js_path

with mkdocs_gen_files.open("javascripts/mermaid_zoom.js", "w") as f:
    f.write(mermaid_zoom_js_path().read_text())
