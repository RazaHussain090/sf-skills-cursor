# Salesforce skills for Cursor

This repository is a local Cursor marketplace of Salesforce builder plugins. Cursor reads [`.cursor-plugin/marketplace.json`](.cursor-plugin/marketplace.json) and installs plugins from [`cursor-plugins/`](cursor-plugins/).

## Install

1. Open **Customize** in the sidebar.
2. Choose **Add → From Local Repo**.
3. Select this repository root (the folder that contains `.cursor-plugin/marketplace.json`) and confirm.
4. Open **Browse Marketplace**, find the **Salesforce** marketplace, and install the plugins you want. Start with **salesforce-development**.
5. Start a new Cursor session so the installed skills register.

You need **Node.js** and the **Salesforce CLI** (`sf`), authenticated to the org you want to use. On Windows the deploy gate also needs **Git Bash** and **Python 3.8 or newer**. It does not use the Windows Subsystem for Linux launcher (`System32\bash.exe`).

Cursor caches the marketplace from the checkout. After you pull new changes, uninstall the plugins, remove the local marketplace, add the repo again, and reinstall.

## Use the plugins

Ask for the task in chat. Installed skills are available to the agent. You do not paste skill files in.

A production deploy is blocked until you reply with exactly:

```text
confirm production deploy to <alias>
```

Use the org alias from the denial, then the same deploy runs again. A scratch org or sandbox deploy does not need that phrase.

Plugin loading, hooks, and maintainer notes are in [`cursor-plugins/README.md`](cursor-plugins/README.md).

## Test Drive

Test Drive runs a curated end-to-end build in your org. The agent checks that you are ready, connects or helps you sign up for an org, then builds the real thing.

Install these plugins, in this order, then start a new session:

| Plugin | Why |
|---|---|
| `salesforce-development` | Required for every drive. It deploys metadata, runs Apex, and checks the toolchain. |
| `salesforce-test-drive` | The `start` command and the drive catalog. |
| `agentforce-adlc` | Required by the service help agent drive. |

In chat, run:

```text
/salesforce-test-drive:start
```

That opens the catalog menu. To skip the menu:

```text
/salesforce-test-drive:start service-help-agent
```

Add `--instrument` to write a friction log (`session-log-<YYYYMMDD-HHMM>.md` in the current directory). A normal start does not create that file.

If `salesforce-development` is not installed, the command stops and tells you to install it.

The current drive, `service-help-agent`, builds an Agentforce service agent that answers FAQs, looks up and updates cases, and escalates to a person, delivered as a website chat widget. It needs an Agentforce-enabled org (a free Agentforce Developer Edition from [developer.salesforce.com/signup](https://developer.salesforce.com/signup) works), API 66.0 or newer, and the Agentforce Service Agent User and Agentforce Service Agent Builder licenses. The agent is deployed as a draft. At the end you get a command to preview it yourself.

The full walkthrough — org connection, the production-deploy pause, resuming an interrupted drive, and where the files live — is in [`cursor-plugins/salesforce-test-drive/README.md`](cursor-plugins/salesforce-test-drive/README.md).
