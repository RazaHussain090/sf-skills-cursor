#!/usr/bin/env python3
"""Translate Cursor hook JSON into the existing LWC and Agentforce hook scripts.

Advisory hooks fail open. The Agentforce shell guard fails closed in the
manifest; this process still returns allow for commands the guard does not block.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _python() -> list:
    return [sys.executable]


def _run(script: Path, payload: dict, cwd: str) -> dict:
    if not script.is_file():
        return {}
    try:
        completed = subprocess.run(
            [*_python(), str(script)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=cwd or None,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    try:
        parsed = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _message(result: dict) -> str:
    specific = result.get("hookSpecificOutput") or {}
    return specific.get("permissionDecisionReason") or specific.get("additionalContext") or ""


def guard(payload: dict) -> dict:
    command = payload.get("command") if isinstance(payload, dict) else ""
    if not isinstance(command, str) or not command:
        return {"permission": "allow"}
    script = PLUGIN_ROOT / "shared" / "hooks" / "scripts" / "guardrails.py"
    if not script.is_file():
        reason = "The Agentforce guardrail script is missing, so this command is blocked."
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    if cwd and Path(cwd).is_dir():
        os.chdir(cwd)
    result = _run(
        script,
        {"tool_name": "Bash", "tool_input": {"command": command}},
        cwd,
    )
    decision = (result.get("hookSpecificOutput") or {}).get("permissionDecision")
    if decision == "deny":
        reason = _message(result) or "Blocked by Agentforce guardrails."
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    note = _message(result)
    out = {"permission": "allow"}
    if note:
        out["agent_message"] = note
    return out


def _file_payload(payload: dict, tool_name: str) -> tuple:
    path = payload.get("file_path") if isinstance(payload, dict) else ""
    if not isinstance(path, str):
        path = ""
    return path, {"tool_name": tool_name, "tool_input": {"file_path": path}}


def validate_agent(payload: dict) -> dict:
    path, wrapped = _file_payload(payload, "Write")
    if not path.endswith(".agent"):
        return {}
    cwd = str(Path(path).parent)
    result = _run(
        PLUGIN_ROOT / "shared" / "hooks" / "scripts" / "agent-validator.py",
        wrapped,
        cwd,
    )
    note = _message(result)
    return {"additional_context": note} if note else {}


def validate_lwc(payload: dict) -> dict:
    path, wrapped = _file_payload(payload, "Write")
    if Path(path).suffix.lower() not in {".html", ".css", ".js"}:
        return {}
    script = PLUGIN_ROOT / "skills" / "experience-lwc-generate" / "scripts" / "post-tool-validate.py"
    result = _run(script, wrapped, str(Path(path).parent) if path else "")
    note = _message(result) or result.get("systemMessage") or ""
    return {"additional_context": note} if note else {}


def main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if mode == "guard":
        print(json.dumps(guard(payload)))
    elif mode == "agent":
        print(json.dumps(validate_agent(payload)))
    elif mode == "lwc":
        print(json.dumps(validate_lwc(payload)))
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        if mode == "guard":
            print(json.dumps({
                "permission": "deny",
                "user_message": "The Agentforce guardrail failed, so this command is blocked.",
                "agent_message": "The Agentforce guardrail failed, so this command is blocked.",
            }))
        else:
            print("{}")
        raise SystemExit(0)
