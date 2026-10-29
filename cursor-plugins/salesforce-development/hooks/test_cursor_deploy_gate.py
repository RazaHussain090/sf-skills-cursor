#!/usr/bin/env python3
"""Unit tests for the Cursor deploy-gate adapter. No org and no bash required."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent


def repo_root() -> Path:
    for parent in HOOKS.parents:
        if (parent / "cursor-plugins" / "generate.py").is_file():
            return parent
    raise RuntimeError("repo root not found")


SCRIPTS = repo_root() / "cursor-plugins" / "salesforce-development" / "scripts"
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(SCRIPTS))

import cursor_deploy_gate as gate
import sf_shim as shim


class DeployGateTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _gate(self, mode, command, target, confirmed, cwd):
        self.calls.append((mode, command, target, confirmed, cwd))
        return {"continue": True, "systemMessage": "allowed"}

    def test_non_deploy_allows_without_calling_the_gate(self):
        result = gate.evaluate_shell(
            {"command": "git status", "cwd": "D:/repo"},
            shim=shim,
            gate=self._gate,
            peek=lambda *_: False,
            consume=lambda *_: True,
            default_org=lambda: ("dev", ""),
        )
        self.assertEqual(result["permission"], "allow")
        self.assertEqual(self.calls, [])

    def test_eval_wrapped_deploy_is_denied_before_the_gate(self):
        result = gate.evaluate_shell(
            {"command": "eval sf project deploy start --target-org prod"},
            shim=shim,
            gate=self._gate,
            peek=lambda *_: False,
            consume=lambda *_: True,
            default_org=lambda: ("dev", ""),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertEqual(self.calls, [])

    def test_literal_deploy_uses_cursor_confirmation_peek(self):
        def peek(session, target):
            self.assertEqual(session, "conv-1")
            self.assertEqual(target, "prod")
            return True

        def consume(session, target):
            self.assertEqual((session, target), ("conv-1", "prod"))
            return True

        def run_gate(mode, command, target, confirmed, cwd):
            self.calls.append((mode, target, confirmed))
            return {"continue": True, "systemMessage": "production", "prodConfirmationUsed": True}

        result = gate.evaluate_shell(
            {
                "command": "sf project deploy start --target-org prod",
                "cwd": "D:/repo",
                "conversation_id": "conv-1",
            },
            shim=shim,
            gate=run_gate,
            peek=peek,
            consume=consume,
            default_org=lambda: ("other", ""),
        )
        self.assertEqual(result["permission"], "allow")
        self.assertEqual(self.calls, [("prod-check", "prod", True)])

    def test_gate_deny_is_mapped(self):
        def run_gate(*_args):
            return {"hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "blocked",
            }}

        result = gate.evaluate_shell(
            {"command": "sf project delete source --target-org prod"},
            shim=shim,
            gate=run_gate,
            peek=lambda *_: False,
            consume=lambda *_: True,
            default_org=lambda: ("dev", ""),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("blocked", result["user_message"])

    def test_confirm_phrase_is_recorded_and_prompt_continues(self):
        seen = []

        def record(session, prompt):
            seen.append((session, prompt))

        result = gate.evaluate_prompt(
            {"prompt": "confirm production deploy to prod", "conversation_id": "conv-9"},
            record=record,
        )
        self.assertEqual(result, {"continue": True})
        self.assertEqual(seen, [("conv-9", "confirm production deploy to prod")])

    def test_wsl_bash_is_not_selected(self):
        self.assertTrue(gate._is_wsl_or_store_bash(r"C:\Windows\System32\bash.exe"))
        self.assertTrue(gate._is_wsl_or_store_bash(
            r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\bash.exe"))
        self.assertFalse(gate._is_wsl_or_store_bash(r"C:\Program Files\Git\bin\bash.exe"))
        found = gate._bash()
        if not found:
            self.skipTest("no usable bash")
        self.assertFalse(gate._is_wsl_or_store_bash(found))

    def test_adapter_failure_allows_a_non_deploy(self):
        result = gate.failure_decision(
            {"command": "sf org display"},
            "the adapter failed",
        )
        self.assertEqual(result["permission"], "allow")

    def test_adapter_failure_denies_a_deploy(self):
        result = gate.failure_decision(
            {"command": "sf project deploy start --target-org prod"},
            "the adapter failed",
        )
        self.assertEqual(result["permission"], "deny")

    def test_powershell_wrapped_deploy_is_denied_before_the_gate(self):
        result = gate.evaluate_shell(
            {"command": 'powershell.exe -NoProfile -Command "sf project deploy start --target-org prod"'},
            shim=shim,
            gate=self._gate,
            peek=lambda *_: False,
            consume=lambda *_: True,
            default_org=lambda: ("dev", ""),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertEqual(self.calls, [])

    def test_real_gate_allows_scratch_and_denies_unconfirmed_production(self):
        if not gate._bash():
            self.skipTest("no usable bash")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            org_file = root / "org.json"
            fake_dir = root / "bin"
            fake_dir.mkdir()
            sf = fake_dir / "sf"
            sf.write_text("#!/bin/sh\ncat \"$SF_FAKE_ORG_FILE\"\n", encoding="utf-8", newline="\n")
            sf.chmod(sf.stat().st_mode | stat.S_IEXEC)
            original = os.environ.copy()
            try:
                os.environ["PATH"] = gate._posix_path(fake_dir) + ":/usr/bin"
                os.environ.pop("SF_TARGET_ORG", None)
                os.environ.pop("SFDX_TARGET_ORG", None)
                os.environ["SF_FAKE_ORG_FILE"] = gate._posix_path(org_file)
                org_file.write_text(json.dumps({
                    "result": {
                        "scratchOrgs": [{
                            "alias": "scratch",
                            "isScratch": True,
                            "instanceUrl": "https://example.scratch.my.salesforce.com",
                        }],
                    },
                }), encoding="utf-8")
                allowed = gate.evaluate_shell(
                    {
                        "command": "sf.cmd project deploy start --target-org scratch",
                        "cwd": str(root),
                        "conversation_id": "conv-scratch",
                    },
                    shim=shim,
                    gate=gate._run_gate,
                    peek=lambda *_: False,
                    consume=lambda *_: True,
                    default_org=lambda: ("", "unset"),
                )
                self.assertEqual(allowed["permission"], "allow", allowed)
                org_file.write_text(json.dumps({
                    "result": {
                        "nonScratchOrgs": [{
                            "alias": "prod",
                            "isScratch": False,
                            "isSandbox": False,
                            "instanceUrl": "https://acme.my.salesforce.com",
                        }],
                    },
                }), encoding="utf-8")
                denied = gate.evaluate_shell(
                    {
                        "command": "sf project deploy start --target-org prod",
                        "cwd": str(root),
                        "conversation_id": "conv-prod",
                    },
                    shim=shim,
                    gate=gate._run_gate,
                    peek=lambda *_: False,
                    consume=lambda *_: True,
                    default_org=lambda: ("", "unset"),
                )
                self.assertEqual(denied["permission"], "deny", denied)
                self.assertIn("Production", denied["user_message"])
            finally:
                os.environ.clear()
                os.environ.update(original)

    def test_guard_denies_when_its_script_is_missing(self):
        path = repo_root() / "cursor-plugins" / "tooling" / "cursor_advisory.py"
        spec = importlib.util.spec_from_file_location("cursor_advisory_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.guard({"command": "sf agent publish"})
        self.assertEqual(result["permission"], "deny")
        self.assertIn("missing", result["user_message"])


if __name__ == "__main__":
    unittest.main()
