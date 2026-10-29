#!/usr/bin/env python3
"""Cursor payload adapter for the salesforce-development deploy gate.

Translates Cursor hook JSON into one call to scripts/sf-deploy-gate. The confirm
phrase, org buckets, and production check stay in that gate.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLIENT = "cursor"


def _scripts_dir() -> Path:
    return PLUGIN_ROOT / "scripts"


def _load_shim():
    scripts = _scripts_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import sf_shim as shim
    return shim


def _load_context():
    scripts = _scripts_dir()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import sf_context as context
    return context


def allow(message: str = "") -> dict:
    out = {"permission": "allow"}
    if message:
        out["agent_message"] = message
    return out


def deny(message: str) -> dict:
    return {
        "permission": "deny",
        "user_message": message,
        "agent_message": message,
    }


def continue_prompt() -> dict:
    return {"continue": True}


def _command(payload: dict) -> str:
    command = payload.get("command")
    return command if isinstance(command, str) else ""


def _cwd(payload: dict) -> str:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd and Path(cwd).is_dir():
        return str(Path(cwd).resolve())
    return ""


def _session_id(payload: dict) -> str:
    for key in ("conversation_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _is_wsl_or_store_bash(path: str) -> bool:
    """Windows Subsystem for Linux and the Store stub cannot run this repo's bash gate."""
    normalized = path.replace("/", "\\").lower()
    return (
        normalized.endswith("\\system32\\bash.exe")
        or normalized.endswith("\\sysnative\\bash.exe")
        or "\\windowsapps\\bash.exe" in normalized
    )


def _posix_path(path: Path) -> str:
    """Git Bash path for a Windows file. Other platforms keep the native path."""
    text = str(path)
    if os.name == "nt" and len(text) > 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text


def _bash_candidates() -> list:
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.append(str(git_path.parent.parent / "bin" / "bash.exe"))
        candidates.append(str(git_path.parent / "bash.exe"))
    return candidates


def _bash() -> str:
    """Bash that can execute sf-deploy-gate. Never the WSL launcher."""
    override = os.environ.get("CURSOR_GATE_BASH", "")
    if override and Path(override).is_file() and not _is_wsl_or_store_bash(override):
        return override
    if os.name == "nt":
        for candidate in _bash_candidates():
            if Path(candidate).is_file():
                return str(Path(candidate))
        found = shutil.which("bash")
        if found and not _is_wsl_or_store_bash(found):
            return found
        return ""
    return shutil.which("bash") or ""


_GATED_COMMAND = re.compile(
    r"\b(?:sf|sfdx)(?:\.cmd|\.exe|\.bat)?\b[\s\S]{0,400}\b(?:deploy|delete)\b"
    r"|\bproject\s+(?:deploy|delete)\b",
    re.IGNORECASE,
)


def command_is_gated(command: str, shim=None) -> bool:
    if shim is not None:
        try:
            if shim.mutation_hint(command):
                return True
        except Exception:
            pass
    return bool(_GATED_COMMAND.search(command or ""))


def failure_decision(payload: dict, message: str) -> dict:
    """Deny a broken adapter only for deploy and delete. Other commands stay allowed."""
    command = _command(payload) if isinstance(payload, dict) else ""
    shim = None
    try:
        shim = _load_shim()
    except Exception:
        shim = None
    if command_is_gated(command, shim):
        return deny(message)
    if isinstance(payload, dict) and not command:
        raw = json.dumps(payload, default=str)
        if command_is_gated(raw, shim):
            return deny(message)
    return allow()


def _looks_like_mutation(shim, command: str) -> bool:
    return bool(command) and shim.mutation_hint(command)


def evaluate_shell(payload: dict, *, shim, gate, peek, consume, default_org) -> dict:
    """Decide one beforeShellExecution event. Callables are injected for tests."""
    command = _command(payload)
    if not isinstance(payload, dict):
        return deny("This shell request has an unrecognized shape, so its Salesforce CLI command cannot be checked.")
    if not command:
        raw = json.dumps(payload, default=str)
        if shim.mutation_hint(raw):
            return deny("This shell request has an unrecognized shape, so its Salesforce CLI command cannot be checked. Run it as one plain shell command.")
        return allow()

    scan = shim.scan_sf(command)
    hinted = _looks_like_mutation(shim, command)
    if scan.untraced or (hinted and (
            scan.opaque or scan.unparsed
            or not any(shim.mutation_verb(call.argv) for call in scan.calls))):
        if hinted or scan.untraced:
            return deny("Run deploy/delete as a literal sf command, not through eval, a nested shell, command substitution, xargs, a heredoc or another wrapper, so its target org can be verified.")
        return allow()
    if scan.repeating and any(shim.mutation_verb(call.argv) for call in scan.calls):
        return deny("Run deploy/delete as one plain top-level sf command, not inside a loop, function or `watch`, so each run is verified and confirmed.")

    mutations = [call for call in scan.calls if shim.mutation_verb(call.argv)]
    if not mutations:
        return allow()
    if shim.mutation_context_is_ambiguous(command):
        return deny("Run deploy/delete without inline directory, environment, config changes or shell-expanded arguments. Use the tool cwd and a literal target org.")
    if len(mutations) != 1:
        return deny("Run one deploy/delete command per shell call so each org is verified.")

    call = mutations[0]
    verb = shim.mutation_verb(call.argv)
    if verb not in ("deploy-start", "deploy-quick", "delete"):
        return allow()

    targets, ambiguous = shim.target_orgs(call.argv)
    if ambiguous or call.xargs:
        return deny("The target org of this deploy/delete cannot be read. Pass one literal --target-org <alias>.")
    if len(targets) > 1:
        return deny("Conflicting target-org flags cannot be verified safely.")
    target = targets[0] if targets else ""
    if not target:
        target, error = default_org()
        if error:
            return deny(f"The target org could not be resolved ({error}). Run 'sf config set target-org <alias>' before deploying.")
    if not target:
        return deny("No target org configured. Run 'sf config set target-org <alias>' before deploying.")

    mode = "destructive" if verb == "delete" else "prod-check"
    confirmed = False
    if mode == "prod-check":
        confirmed = bool(peek(_session_id(payload), target))
    result = gate(mode, command, target, confirmed, _cwd(payload))
    decision = (result.get("hookSpecificOutput") or {}).get("permissionDecision")
    if decision == "deny":
        reason = (result.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or "Deploy blocked."
        return deny(reason)
    if result.get("continue") is True or result.get("systemMessage"):
        if confirmed and result.get("prodConfirmationUsed"):
            if not consume(_session_id(payload), target):
                return deny(f'The production deploy confirmation was already used. Ask the user to reply "confirm production deploy to {target}" again.')
        message = result.get("systemMessage") or ""
        return allow(message)
    return deny("The deploy gate did not evaluate this command.")


def evaluate_prompt(payload: dict, *, record) -> dict:
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str):
        return continue_prompt()
    record(_session_id(payload), prompt)
    return continue_prompt()


def _run_gate(mode: str, command: str, target: str, confirmed: bool, cwd: str) -> dict:
    bash = _bash()
    gate = _scripts_dir() / "sf-deploy-gate"
    if not bash or not gate.is_file():
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "[salesforce-development · deploy-gate] bash or sf-deploy-gate is missing, so this deploy/delete is blocked.",
            }
        }
    args = [bash, str(gate), mode, "--matched", "--target", target, "--client", CLIENT]
    if confirmed:
        args.append("--confirmed")
    payload = json.dumps({"tool_input": {"command": command}})
    # Git Bash must see the interpreter the Node launcher already resolved.
    # MSYS path conversion would rewrite that absolute path.
    env = {
        **os.environ,
        "FORCE_COLOR": "0",
        "NO_COLOR": "1",
        "MSYS_NO_PATHCONV": "1",
        "MSYS2_ARG_CONV_EXCL": "*",
        "SF_DEPLOY_GATE_PYTHON": _posix_path(Path(sys.executable)),
    }
    try:
        completed = subprocess.run(
            args,
            input=payload,
            text=True,
            capture_output=True,
            cwd=cwd or None,
            timeout=35,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "[salesforce-development · deploy-gate] the deploy gate failed to run, so this deploy/delete is blocked.",
            }
        }
    try:
        parsed = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "[salesforce-development · deploy-gate] the deploy gate did not return a decision, so this deploy/delete is blocked.",
            }
        }
    return parsed


def _real_default_org():
    context = _load_context()
    return context.get_target_org_detailed()


def _real_peek(session_id: str, target: str) -> bool:
    return bool(_load_context()._peek_prod_deploy_confirmation(session_id, target, CLIENT))


def _real_consume(session_id: str, target: str) -> bool:
    return bool(_load_context()._consume_prod_deploy_confirmation(session_id, target, CLIENT))


def _real_record(session_id: str, prompt: str) -> None:
    context = _load_context()
    alias = context._prod_deploy_confirmation_alias(prompt)
    if not alias or not session_id:
        return
    resolved = context._plugin_session_id(session_id, CLIENT)
    context._record_prod_deploy_confirmation(resolved, alias)


def main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {"command": raw}
    if not isinstance(payload, dict):
        payload = {"command": raw}
    try:
        cwd = _cwd(payload)
        if cwd:
            try:
                os.chdir(cwd)
            except OSError:
                pass
        if mode == "confirm":
            print(json.dumps(evaluate_prompt(payload, record=_real_record)))
            return 0
        if mode != "deploy":
            print(json.dumps(deny("Unknown Cursor deploy-gate mode.")))
            return 0
        shim = _load_shim()
        print(json.dumps(evaluate_shell(
            payload,
            shim=shim,
            gate=_run_gate,
            peek=_real_peek,
            consume=_real_consume,
            default_org=_real_default_org,
        )))
        return 0
    except Exception:
        print(json.dumps(failure_decision(
            payload,
            "[salesforce-development · deploy-gate] the Cursor adapter failed, so this deploy/delete is blocked.",
        )))
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
