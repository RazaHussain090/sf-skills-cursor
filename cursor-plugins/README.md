# Salesforce Cursor plugins

This tree is the only plugin catalog in the repository. Each plugin directory contains the skills, scripts, and Cursor manifest that Cursor installs.

## Install and use

Cursor reads [`.cursor-plugin/marketplace.json`](../.cursor-plugin/marketplace.json) at the repository root. That file points `pluginRoot` at this folder.

1. Open **Customize** in the sidebar.
2. Choose **Add → From Local Repo**.
3. Select this repository root, the directory that contains `.cursor-plugin/marketplace.json`, and confirm.
4. Open **Browse Marketplace**, find the Salesforce marketplace, and install the plugins you want. Start with **salesforce-development**. Install **salesforce-test-drive** only after that one.

Cursor caches the marketplace from the checkout. After you pull, uninstall the plugins, remove the local marketplace, and add the repo again.

You need Node, and the Salesforce CLI (`sf`) authenticated against the org you want to use. On Windows the deploy gate also needs Git Bash and Python 3.8 or newer. The Windows Subsystem for Linux launcher (`System32\bash.exe`) is not used.

Then work in a Salesforce project the way you already would:

- Ask for the task in chat. Installed skills are available to the agent. You do not paste skill files in.
- A production deploy is blocked until you reply with exactly `confirm production deploy to <alias>`, using the org alias from the denial, and the same deploy is run again.
- A scratch org or sandbox deploy does not need that phrase.
- The Test Drive `start` command walks through a rehearsed build. Its text tells the agent to stop when Salesforce Development is not installed. That instruction is not a hook.

## Maintainers

`python cursor-plugins/generate.py` copies the shared hook launchers from `tooling/` into the plugins that use them. `python cursor-plugins/generate.py --check` fails when those copies drift.

## What each plugin loads

| Plugin | Cursor contents |
|---|---|
| Every plugin that has skills | Existing `skills/` |
| `salesforce-code-quality`, `agentforce-adlc`, `salesforce-development` | `cursor-agents/` with `name` and `description` |
| `salesforce-development` | MCP servers for API context, metadata experts, and the Apex/SOQL language server. `beforeShellExecution` runs `sf-deploy-gate` with `--client cursor`. A production deploy is allowed only after the user sends `confirm production deploy to <alias>`. |
| `experience-lwc` | Advisory LWC validation after a file edit |
| `agentforce-adlc` | Shell guardrail and `.agent` validator. A missing guardrail script denies the command. |
| `salesforce-test-drive` | `start` command. Its text tells the agent to stop when `salesforce-development` is not available. That is an instruction to the model, not a hook. |

Node is required for the hook launcher and the MCP servers. The deploy gate runs under Git Bash on Windows, not the `System32\bash.exe` Windows Subsystem for Linux launcher, and it uses the Python interpreter the Node launcher already found (`SF_DEPLOY_GATE_PYTHON`). If bash or that interpreter is missing, a deploy or delete is denied. A non-deploy command is allowed when the adapter itself fails. A crash of the hook process is still fail-closed for commands the matcher selected.

Plugin recommendation, telemetry, and the feedback nudge are not part of these plugins.
