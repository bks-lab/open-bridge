# SPDX-License-Identifier: MIT
"""bridge_cockpit: the Bridge cockpit, a local web page that watches and steers the Bridge, served by scripts/bridge-cockpit.py.

The server collects the briefing with the Bridge's scripts
(briefing.py collect --no-save, workplace.py, inbox.py, task.py), turns the result
into a view model (model.py, originally ported from the retired briefing-ui mod), pushes it to
the browser over server-sent events and runs a fixed set of verbs on a click.
It binds 127.0.0.1 only and asks for a per-start token. User doc: docs/bridge-cockpit.md.
"""

VERSION = "0.1.0"
