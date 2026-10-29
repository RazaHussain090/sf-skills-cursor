#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const mode = process.argv[2] || "";
const hookDir = path.dirname(fs.realpathSync(__filename));

function emit(value, status) {
  process.stdout.write(JSON.stringify(value));
  process.exit(status);
}

function pythonCommand() {
  const checks = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, args] of checks) {
    const probe = spawnSync(cmd, [...args, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (probe.status === 0) return [cmd, args];
  }
  return null;
}

function scriptFor(kind) {
  if (kind === "deploy" || kind === "confirm") {
    return path.join(hookDir, "cursor_deploy_gate.py");
  }
  return path.join(hookDir, "cursor_advisory.py");
}

function commandText(raw) {
  try {
    const payload = JSON.parse(raw || "{}");
    return typeof payload.command === "string" ? payload.command : "";
  } catch (_error) {
    return "";
  }
}

function isDeployCommand(text) {
  return /\b(sf|sfdx)(\.cmd|\.exe|\.bat)?\b[\s\S]{0,400}\b(deploy|delete)\b/i.test(text)
    || /\bproject\s+(deploy|delete)\b/i.test(text);
}

function isGatedCommand(kind, text) {
  if (kind === "guard") {
    return isDeployCommand(text) || /\b(DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b/.test(text);
  }
  return isDeployCommand(text);
}

function fallback(kind, raw) {
  if (kind === "confirm") return { continue: true };
  if ((kind === "deploy" || kind === "guard") && isGatedCommand(kind, commandText(raw))) {
    return {
      permission: "deny",
      user_message: "Python 3 is required to run this Salesforce safety hook, so this deploy or delete is blocked.",
      agent_message: "Python 3 is required to run this Salesforce safety hook, so this deploy or delete is blocked.",
    };
  }
  if (kind === "deploy" || kind === "guard") return { permission: "allow" };
  return {};
}

const input = fs.readFileSync(0, "utf8");
const python = pythonCommand();
const script = scriptFor(mode);
if (!python || !fs.existsSync(script)) {
  emit(fallback(mode, input), 0);
}

const [cmd, args] = python;
const child = spawnSync(cmd, [...args, script, mode], {
  input,
  encoding: "utf8",
  windowsHide: true,
  cwd: hookDir,
});
if (child.status !== 0 || !child.stdout) {
  emit(fallback(mode, input), 0);
}
process.stdout.write(child.stdout);
process.exit(0);
