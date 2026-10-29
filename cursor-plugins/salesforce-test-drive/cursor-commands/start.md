---
name: start
description: Start the Salesforce Test Drive. Stops when the salesforce-development plugin is not installed, then runs the rehearsable end-to-end engine.
---

# Start a Salesforce test drive

Stop before doing anything else when the `salesforce-development` plugin is not available in this session. The drive choreographs that plugin's skills. Tell the user to install `salesforce-development` from the Salesforce Cursor marketplace and start a new session. Do not scaffold, deploy, or open the menu.

When `salesforce-development` is available:

1. Set `PLUGIN_ROOT` to the `salesforce-test-drive` plugin directory, the folder that contains `references/engine.md`.
2. Read `references/engine.md` from that directory and follow it from start to finish.
3. Parse the user's arguments: an optional test-drive id, and an optional `--instrument` flag.
4. If an id was named, pass it as `SELECTED_DRIVE`. Otherwise leave `SELECTED_DRIVE` empty so the engine shows the catalog menu.
5. Pass `--instrument` through only when the user set it.

The engine owns readiness, org connection, the menu, and the build. Do not reimplement it.
