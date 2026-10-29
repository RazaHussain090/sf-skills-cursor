# Salesforce Test Drive

Take a Salesforce capability for a test drive. You pick a curated end-to-end build from a menu, and the agent checks that you are ready, connects or helps you sign up for an org, then builds the real thing in that org.

The first drive builds an Agentforce service help agent and leaves it as a website chat widget you can preview.

## What you need

- **Cursor**, with this repository opened or added as a local marketplace.
- **Node.js**, used by the companion plugin's skills.
- **Salesforce CLI** (`sf`), authenticated to the org you want to build in. If you do not have an org yet, the drive points you at a free signup.
- On **Windows**, Git Bash and Python 3.8 or newer. The deploy gate uses Git Bash. The Windows Subsystem for Linux launcher (`System32\bash.exe`) is not used.

Install these plugins from the Salesforce marketplace, in this order, then start a **new Cursor session** so their skills register:

| Plugin | Why |
|---|---|
| `salesforce-development` | Required for every drive. It deploys metadata, runs Apex, and checks the toolchain. |
| `salesforce-test-drive` | The `start` command and the drive catalog. |
| `agentforce-adlc` | Required by the service help agent drive. Install it before you start that drive. |

## Install

Cursor reads `.cursor-plugin/marketplace.json` at the repository root. That file points the marketplace at `cursor-plugins/`.

1. Open **Customize** in the sidebar.
2. Choose **Add → From Local Repo**.
3. Select this repository root (the folder that contains `.cursor-plugin/marketplace.json`) and confirm.
4. Open **Browse Marketplace**, find the **Salesforce** marketplace, and install **salesforce-development**, then **salesforce-test-drive**. Install **agentforce-adlc** as well if you want the service help agent.
5. Start a new Cursor session.

Cursor caches the marketplace from the checkout. After you pull new changes, uninstall the plugins, remove the local marketplace, add the repo again, and reinstall.

## Start a drive

In chat, run:

```text
/salesforce-test-drive:start
```

That opens the catalog menu. Pick a drive, or choose **Not now** to leave.

To skip the menu and run one drive by id:

```text
/salesforce-test-drive:start service-help-agent
```

To also write a session log of CLI calls, pauses, and errors (for measuring friction, not for a normal demo):

```text
/salesforce-test-drive:start service-help-agent --instrument
```

The log is written as `session-log-<YYYYMMDD-HHMM>.md` in the current directory. A normal start does not create that file.

If `salesforce-development` is not installed, the command stops and tells you to install it. It does not scaffold a project or open the menu.

## What a drive does

You stay in the conversation. The agent narrates each check, then builds.

1. Confirms `salesforce-development` is installed and its skills are available in this session.
2. Checks the Salesforce CLI, Node, and Git. A missing CLI or Node stops the drive. Other gaps are mentioned and the drive continues.
3. Looks for a connected org. If one is already the default, it uses that org. If several are authenticated and none is the default, it asks which one to use. If none are connected, it sends you to [developer.salesforce.com/signup](https://developer.salesforce.com/signup) for the edition the drive needs, then connects it:

   ```bash
   sf org login web --alias test-drive --set-default
   ```

4. Gates the drive on its requirements (extra plugins, API version, licenses). A missing plugin is installed from this marketplace; you then start a new session and run the same `start` command again.
5. Builds and deploys to the default org. It pauses only for design choices and for Setup steps it cannot do from the CLI. When it pauses, it tells you what to click. Reply **continue** when that step is done.
6. Hands you a copy-paste command to try the result yourself. It does not run the preview for you.

A Developer Edition or trial org can be classified as production. If the deploy pauses, reply with exactly:

```text
confirm production deploy to <alias>
```

Use the org alias from the denial, then the same deploy runs again. A scratch org or sandbox does not need that phrase.

If a drive is interrupted, say **continue** or **pick it back up**. The companion plugin points you back at `/salesforce-test-drive:start <id>`.

## Drives in the catalog

| Id | What it builds | Extra plugin | Org |
|---|---|---|---|
| `service-help-agent` | An Agentforce service agent that answers FAQs, looks up and updates cases, and escalates to a person, delivered as a website chat widget. | `agentforce-adlc` | Agentforce-enabled org (a free Agentforce Developer Edition works). API 66.0 or newer. Licenses: Agentforce Service Agent User, Agentforce Service Agent Builder. |

The agent is deployed as a **draft**. It is not published or activated. At the end, the agent gives you one command to preview it from the local authoring bundle, with live Apex actions. Run that command yourself in a terminal from the project it names. Then ask a common question, ask it to open a case, and ask to talk to a person.

Wiring the agent to Messaging for Web / Embedded Service on a real website is a Setup step the drive narrates. It is not automated.

## Where things live

| Path | Role |
|---|---|
| `cursor-commands/start.md` | The `/salesforce-test-drive:start` command. |
| `references/engine.md` | Readiness, org connection, the menu, and the build. The command follows this file. |
| `catalog/test-drives.json` | Drive titles, requirements, and the handoff text. |
| `prompts/` | The prompt each drive runs, as if you had typed it. |
| `references/instrumentation.md` | What `--instrument` records. |
