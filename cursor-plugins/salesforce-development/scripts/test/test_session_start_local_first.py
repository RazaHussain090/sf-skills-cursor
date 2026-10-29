#!/usr/bin/env python3
"""Behavior proofs for bounded, subprocess-free SessionStart discovery."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from _test_support import load_module, strip_ansi

SCRIPTS = Path(__file__).resolve().parent.parent
sfx = load_module(SCRIPTS / "sf_context.py", "session_start_local_first_context")


class SessionStartLocalFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.home = self.root / "home"
        self.project.mkdir()
        self.home.mkdir()
        self.old_cwd = Path.cwd()
        os.chdir(self.project)
        self.home_patch = mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def make_project(self):
        (self.project / "sfdx-project.json").write_text(json.dumps({
            "name": "local-first",
            "sourceApiVersion": "64.0",
            "packageDirectories": [{"path": "force-app"}],
        }), encoding="utf-8")

    def configure_target(self, alias="local-dev"):
        config = self.project / ".sf" / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"target-org": alias}), encoding="utf-8")

    def add_auth_fact(self):
        auth = self.home / ".sfdx" / "user@example.invalid.json"
        auth.parent.mkdir(parents=True, exist_ok=True)
        auth.write_text(json.dumps({"accessToken": "not-used-by-startup"}), encoding="utf-8")

    def detect(self, source="startup"):
        output = io.StringIO()
        payload = io.StringIO(json.dumps({"source": source, "session_id": "local-first"}))
        with mock.patch.object(sfx.sys, "stdin", payload), redirect_stdout(output):
            self.assertEqual(sfx.cmd_detect(), 0)
        return json.loads(output.getvalue())

    def test_startup_variants_make_zero_external_calls(self):
        cases = ("connected", "configured", "no-target", "non-project", "compact")
        for case in cases:
            with self.subTest(case=case):
                for child in tuple(self.project.iterdir()):
                    if child.is_dir():
                        import shutil
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                self.make_project()
                source = "startup"
                if case in ("connected", "configured"):
                    self.configure_target()
                if case == "connected":
                    self.add_auth_fact()
                if case == "non-project":
                    (self.project / "sfdx-project.json").unlink()
                if case == "compact":
                    source = "compact"

                forbidden = AssertionError("external work on SessionStart")
                with mock.patch.object(sfx.subprocess, "run", side_effect=forbidden) as external, \
                        mock.patch.object(sfx.subprocess, "Popen", side_effect=forbidden) as popen, \
                        mock.patch.object(sfx.os, "system", side_effect=forbidden) as os_system, \
                        mock.patch.object(sfx.urllib.request, "urlopen", side_effect=forbidden) as network, \
                        mock.patch.object(sfx, "fetch_org_info_via_node", side_effect=forbidden) as node_helper, \
                        mock.patch.object(sfx, "get_target_org", side_effect=forbidden) as cli_target, \
                        mock.patch.object(sfx, "get_org_list", side_effect=forbidden) as org_list, \
                        mock.patch.object(sfx, "get_org_display", side_effect=forbidden) as org_display:
                    result = self.detect(source)
                for forbidden_call in (
                    external, popen, os_system, network, node_helper, cli_target,
                    org_list, org_display
                ):
                    self.assertEqual(forbidden_call.call_count, 0)
                if case == "non-project":
                    self.assertNotIn("systemMessage", result)
                elif case == "compact":
                    self.assertNotIn("systemMessage", result)
                else:
                    self.assertIn("systemMessage", result)

    def test_configured_target_is_named_but_never_passively_claimed_reachable(self):
        self.make_project()
        self.configure_target("local-dev")
        result = self.detect()
        visible = strip_ansi(result["systemMessage"])
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("local-dev", visible)
        # The lean org line names the target and offers the status command, making NO
        # reachability claim. The "unprobed" marker no longer prints on the splash —
        # it dropped with the "configured, not probed" descriptor (org line) and the
        # "git status unprobed" git line (project band) — but the unprobed state still
        # rides the model context (below) and the rail org-cell helper.
        self.assertIn("/salesforce-development:status", visible)
        self.assertNotIn("unprobed", visible.lower())
        self.assertNotRegex(visible.lower(), r"\breachable\b|\bunreachable\b")
        state = sfx._derive_journey_state(
            self.project, has_project=True, target="local-dev",
            target_error="unprobed", org_display=None)
        org_cell = sfx._journey_org_cell(state["context"])
        self.assertEqual(org_cell, "org: local-dev (unprobed)")
        self.assertIn("state=configured-unprobed", context)

    def test_no_target_keeps_local_project_header_and_login_guidance(self):
        self.make_project()
        source = self.project / "force-app" / "main" / "default" / "classes"
        source.mkdir(parents=True)
        (source / "Widget.cls").write_text("public class Widget {}", encoding="utf-8")
        result = self.detect()
        visible = strip_ansi(result["systemMessage"])
        self.assertIn("org: none set", visible)   # lean no-org line, not a titled band
        self.assertIn("local-first", visible)
        self.assertIn("sfdx project:", visible)    # project header stays
        self.assertNotIn("Apex 1 src / 0 test", visible)  # inventory row dropped from the splash
        self.assertIn("/salesforce-development:login", visible)

    def test_explicit_status_still_invokes_live_resolver(self):
        self.make_project()
        org = {"alias": "local-dev", "edition": "Developer", "apiVersion": "64.0"}
        with mock.patch.object(sfx, "resolve_executable", return_value="/usr/bin/sf"), \
                mock.patch.object(sfx, "get_target_org_detailed", return_value=("local-dev", "")) as target, \
                mock.patch.object(sfx, "resolve_org_info", return_value=org) as resolver, \
                mock.patch.object(sfx, "git_status_line", return_value=""), redirect_stdout(io.StringIO()):
            self.assertEqual(sfx.cmd_status(), 0)
        target.assert_called_once_with()
        resolver.assert_called_once_with("local-dev")


class ProjectStatsSingleWalkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.write_descriptor([{"path": "force-app"}])

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def write_descriptor(self, package_directories):
        (self.root / "sfdx-project.json").write_text(json.dumps({
            "name": "inventory-test",
            "sourceApiVersion": "64.0",
            "packageDirectories": package_directories,
        }), encoding="utf-8")

    def write_metadata(self, relative, contents="fixture"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_ordinary_project_counts_match_existing_inventory_contract_in_one_walk(self):
        paths = (
            "force-app/main/default/classes/Widget.cls",
            "force-app/main/default/classes/WidgetTest.cls",
            "force-app/main/default/triggers/Widget.trigger",
            "force-app/main/default/lwc/widget/widget.js-meta.xml",
            "force-app/main/default/aura/card/card.cmp-meta.xml",
            "force-app/main/default/objects/Widget__c/Widget__c.object-meta.xml",
            "force-app/main/default/permissionsets/Widget.permissionset-meta.xml",
            "force-app/main/default/flows/Widget.flow-meta.xml",
        )
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        real_walk = os.walk
        real_descriptor_read = sfx._read_project_descriptor
        with mock.patch.object(sfx.os, "walk", wraps=real_walk) as walk, \
                mock.patch.object(
                    sfx, "_read_project_descriptor", wraps=real_descriptor_read
                ) as descriptor_read:
            stats = sfx.project_stats()
        self.assertEqual(walk.call_count, 1)
        self.assertEqual(descriptor_read.call_count, 1)
        self.assertEqual(stats, {
            "apex_src": 1, "apex_test": 1, "triggers": 1, "lwc": 1,
            "aura": 1, "objects": 1, "permsets": 1, "flows": 1,
        })

    def test_metadata_outside_declared_package_directories_is_ignored(self):
        self.write_metadata("force-app/main/default/classes/Inside.cls")
        self.write_metadata("scripts/Outside.cls")
        self.write_metadata("other/main/default/flows/Outside.flow-meta.xml")

        stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)
        self.assertEqual(stats["flows"], 0)

    def test_multiple_nested_and_duplicate_package_roots_count_each_file_once(self):
        self.write_descriptor([
            {"path": "packages/alpha/nested"},
            {"path": "packages/beta"},
            {"path": "packages/alpha"},
            {"path": "packages/alpha"},
        ])
        self.write_metadata("packages/alpha/main/default/classes/Alpha.cls")
        self.write_metadata("packages/alpha/nested/main/default/classes/Nested.cls")
        self.write_metadata("packages/beta/main/default/classes/Beta.cls")
        self.write_metadata("packages/gamma/main/default/classes/Outside.cls")

        real_walk = os.walk
        with mock.patch.object(sfx.os, "walk", wraps=real_walk) as walk:
            stats = sfx.project_stats()

        self.assertEqual(walk.call_count, 1)
        self.assertEqual(stats["apex_src"], 3)

    def test_declared_package_beneath_excluded_directory_is_counted(self):
        self.write_descriptor([{"path": "vendor/pkg"}])
        self.write_metadata("vendor/pkg/main/default/classes/Declared.cls")
        self.write_metadata("vendor/undeclared/main/default/classes/Outside.cls")

        stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)

    def test_nested_declared_root_survives_parent_root_and_excluded_ancestor(self):
        self.write_descriptor([{"path": "."}, {"path": "vendor/pkg"}])
        self.write_metadata("force-app/main/default/classes/Parent.cls")
        self.write_metadata("vendor/pkg/main/default/classes/Nested.cls")
        self.write_metadata("vendor/undeclared/main/default/classes/Outside.cls")

        stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 2)

    def test_many_roots_prune_undeclared_siblings_with_bounded_traversal(self):
        roots = [f"packages/pkg-{index:03d}" for index in range(50)]
        self.write_descriptor([{"path": path} for path in roots])
        for relative in roots:
            (self.root / relative).mkdir(parents=True)
        for index in range(200):
            sibling = self.root / "packages" / f"sibling-{index:03d}"
            (sibling / "deep" / "tree").mkdir(parents=True)
            (sibling / "deep" / "tree" / "Ignored.cls").write_text(
                "fixture", encoding="utf-8"
            )

        real_scandir = os.scandir
        scanned = []

        def counted_scandir(path):
            scanned.append(Path(path).resolve())
            return real_scandir(path)

        with mock.patch.object(sfx.os, "scandir", side_effect=counted_scandir):
            stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 0)
        self.assertLessEqual(len(scanned), 52)  # root + packages + 50 accepted roots
        self.assertFalse(any("sibling-" in path.name for path in scanned), scanned)

    def test_absolute_escaping_non_string_and_missing_package_paths_are_rejected(self):
        absolute = self.root / "absolute-package"
        self.write_descriptor([
            {"path": str(absolute)},
            {"path": "../escaping-package"},
            {"path": 42},
            {},
            "force-app",
            None,
            {"path": "force-app"},
        ])
        self.write_metadata("absolute-package/main/default/classes/Absolute.cls")
        self.write_metadata("force-app/main/default/classes/Inside.cls")

        stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)

    def test_escaping_package_path_is_rejected_directly(self):
        roots = sfx._validated_package_roots(self.root.resolve(), {
            "packageDirectories": [{"path": "../escaping-package"}],
        })

        self.assertEqual(roots, [])

    def test_missing_package_path_is_rejected_directly(self):
        roots = sfx._validated_package_roots(self.root.resolve(), {
            "packageDirectories": [{"path": "missing-package"}],
        })

        self.assertEqual(roots, [])

    def test_regular_file_package_path_is_rejected_directly(self):
        package_file = self.root / "not-a-package-directory"
        package_file.write_text("fixture", encoding="utf-8")
        roots = sfx._validated_package_roots(self.root.resolve(), {
            "packageDirectories": [{"path": package_file.name}],
        })

        self.assertEqual(roots, [])

    @unittest.skipIf(os.name == "nt", "symlink creation is not reliably available on Windows")
    def test_symlink_package_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_package = Path(outside) / "pkg"
            outside_package.mkdir()
            (self.root / "linked-outside").symlink_to(outside_package, target_is_directory=True)

            roots = sfx._validated_package_roots(self.root.resolve(), {
                "packageDirectories": [{"path": "linked-outside"}],
            })

        self.assertEqual(roots, [])

    def test_undeclared_tree_cannot_consume_shared_file_or_entry_caps(self):
        self.write_metadata("a-undeclared/one.txt")
        self.write_metadata("a-undeclared/two.txt")
        for index in range(20):
            (self.root / "a-undeclared" / f"dir-{index}").mkdir()
        self.write_metadata("force-app/main/default/classes/Inside.cls")

        with mock.patch.object(sfx, "_PROJECT_STATS_FILE_CAP", 2), \
                mock.patch.object(sfx, "_PROJECT_STATS_ENTRY_CAP", 5):
            stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)

    def test_file_cap_is_shared_across_declared_package_roots(self):
        self.write_descriptor([{"path": "alpha"}, {"path": "beta"}])
        self.write_metadata("alpha/One.cls")
        self.write_metadata("alpha/Two.trigger")
        self.write_metadata("beta/Three.cls")

        with mock.patch.object(sfx, "_PROJECT_STATS_FILE_CAP", 2):
            stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)
        self.assertEqual(stats["triggers"], 1)

    def test_entry_cap_is_shared_across_declared_package_roots(self):
        self.write_descriptor([{"path": "alpha"}, {"path": "beta"}])
        self.write_metadata("alpha/One.cls")
        self.write_metadata("beta/Three.cls")
        self.write_metadata("beta/Two.trigger")

        with mock.patch.object(sfx, "_PROJECT_STATS_ENTRY_CAP", 4):
            stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)
        self.assertEqual(stats["triggers"], 0)

    def test_depth_cap_applies_to_each_declared_package_root(self):
        self.write_descriptor([{"path": "alpha"}, {"path": "beta"}])
        self.write_metadata("alpha/Shallow.cls")
        self.write_metadata("beta/nested/TooDeep.cls")

        with mock.patch.object(sfx, "_PROJECT_STATS_DEPTH_CAP", 1):
            stats = sfx.project_stats()

        self.assertEqual(stats["apex_src"], 1)

    def test_project_meta_ignores_malformed_package_entries(self):
        self.write_descriptor([
            None, "force-app", 42, {}, {"path": None}, {"path": ["bad"]},
            {"path": ""}, {"path": "force-app"}, {"path": "other"},
        ])
        self.assertEqual(sfx.project_meta()["package_dirs"], "force-app, other")

        for malformed in (None, "force-app", 42, {"path": "force-app"}):
            with self.subTest(package_directories=malformed):
                self.write_descriptor(malformed)
                self.assertEqual(sfx.project_meta()["package_dirs"], "force-app")

    def test_excluded_fifty_thousand_file_tree_is_pruned_before_descent(self):
        (self.root / "force-app").mkdir()

        def synthetic_walk(_root, topdown=True, onerror=None, followlinks=False):
            dirs = ["force-app", "vendor", "node_modules", ".git", ".sf", ".sfdx"]
            yield str(self.root), dirs, []
            self.assertEqual(dirs, ["force-app"])
            yield str(self.root / "force-app"), [], ["Widget.cls"]
            # If an excluded directory survives pruning it represents a 50k-file tree.
            if "vendor" in dirs:
                yield str(self.root / "vendor"), [], [f"junk-{i}.cls" for i in range(50_000)]

        with mock.patch.object(sfx.os, "walk", side_effect=synthetic_walk):
            stats = sfx.project_stats()
        self.assertEqual(stats["apex_src"], 1)

    def test_empty_directory_entries_are_bounded_and_cap_order_is_deterministic(self):
        self.write_descriptor([{"path": "."}])
        yielded = 0

        def empty_tree(_root, topdown=True, onerror=None, followlinks=False):
            nonlocal yielded
            dirs = [f"d-{index:04d}" for index in range(100)]
            yielded += 1
            yield str(self.root), dirs, []
            yielded += 1
            yield str(self.root / "d-0000"), [], []

        with mock.patch.object(sfx, "_PROJECT_STATS_ENTRY_CAP", 10, create=True), \
                mock.patch.object(sfx.os, "walk", side_effect=empty_tree):
            sfx.project_stats()
        self.assertEqual(yielded, 1)

        def ordered(files):
            def walk(_root, topdown=True, onerror=None, followlinks=False):
                yield str(self.root), [], list(files)
            with mock.patch.object(sfx, "_PROJECT_STATS_FILE_CAP", 2), \
                    mock.patch.object(sfx.os, "walk", side_effect=walk):
                return sfx.project_stats()

        files = ["z-junk", "Widget.cls", "a-junk"]
        self.assertEqual(ordered(files), ordered(reversed(files)))

    def test_cap_and_walk_error_return_bounded_partial_counts(self):
        self.write_descriptor([{"path": "."}])

        def capped_walk(_root, topdown=True, onerror=None, followlinks=False):
            yield str(self.root), [], ["One.cls", "Two.trigger", "a", "b", "c"]

        with mock.patch.object(sfx, "_PROJECT_STATS_FILE_CAP", 3), \
                mock.patch.object(sfx.os, "walk", side_effect=capped_walk):
            stats = sfx.project_stats()
        self.assertEqual(stats["apex_src"], 1)
        self.assertEqual(stats["triggers"], 1)

        def failing_walk(_root, topdown=True, onerror=None, followlinks=False):
            yield str(self.root), [], ["One.cls"]
            raise OSError("synthetic read failure")

        with mock.patch.object(sfx.os, "walk", side_effect=failing_walk):
            partial = sfx.project_stats()
        self.assertEqual(partial["apex_src"], 1)


class ColdStartAutoupdateNoticeTests(unittest.TestCase):
    """The pending-CLI-update heads-up: cache-only detection (no subprocess) plus
    the PreToolUse Bash advisory that surfaces it ONLY when an `sf` command is
    about to run — never at SessionStart, so a non-Salesforce session is silent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "sf-cache"
        self.cache.mkdir()
        # Isolate the standalone-client layout too: SF_OCLIF_CLIENT_HOME points at an
        # empty dir with no `current` symlink, so `_installed_cli_client_version()`
        # returns None and detection falls back to the cache's `current` field — the
        # exact npm-install / no-standalone-client path the cache-only tests exercise.
        # Tests of the LIVE-client path create the symlink themselves via write_client.
        self.client = self.root / "sf-client"
        self.client.mkdir()
        self.old_cwd = Path.cwd()
        self.cwd = self.root / "elsewhere"
        self.cwd.mkdir()
        os.chdir(self.cwd)
        # SF_CACHE_DIR pins the cache dir cross-platform; clear the disable/opt-out
        # vars so a developer's own environment can't mask the notice under test.
        self.env = mock.patch.dict(
            os.environ,
            {"SF_CACHE_DIR": str(self.cache), "SF_OCLIF_CLIENT_HOME": str(self.client)},
            clear=False,
        )
        self.env.start()
        for var in ("SF_DISABLE_AUTOUPDATE", "SFDX_DISABLE_AUTOUPDATE",
                    "SFDX_SKIP_CLI_UPDATE_CHECK", "CLAUDE_PLUGIN_OPTION_UI_MODE"):
            os.environ.pop(var, None)
        # Isolate the once-per-session marker dir so it starts empty each test and
        # never leaks across runs (mirrors the discovery-runtime tests).
        self.orig_marker_dir = sfx._WELCOME_MARKER_DIR
        sfx._WELCOME_MARKER_DIR = self.root / "session-markers"

    def tearDown(self):
        sfx._WELCOME_MARKER_DIR = self.orig_marker_dir
        self.env.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def write_version(self, current, latest):
        (self.cache / "version").write_text(
            json.dumps({"current": current, "latest": latest}), encoding="utf-8")

    def write_client(self, version):
        """Create the standalone-client `current` symlink oclif's shim execs, named
        like the real layout (`2.150.6-c049970`), so `_installed_cli_client_version`
        reads the version that will ACTUALLY run — independent of the cache file."""
        target = self.client / f"{version}-c049970"
        target.mkdir(exist_ok=True)
        link = self.client / "current"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)

    def run_hook(self, command="sf template generate project --help", session="cs"):
        """Drive cmd_cli_update_notice with a PreToolUse Bash payload."""
        output = io.StringIO()
        payload = io.StringIO(json.dumps({
            "session_id": session, "tool_name": "Bash",
            "tool_input": {"command": command},
        }))
        with mock.patch.object(sfx.sys, "stdin", payload), redirect_stdout(output):
            self.assertEqual(sfx.cmd_cli_update_notice(), 0)
        return json.loads(output.getvalue())

    # --- cache-only detection -------------------------------------------------

    def test_pending_bump_is_detected_from_cache_without_subprocess(self):
        self.write_version("2.145.6", "2.150.6")
        forbidden = AssertionError("detection must not shell out")
        with mock.patch.object(sfx.subprocess, "run", side_effect=forbidden):
            pending = sfx._pending_cli_update_cached()
        self.assertEqual(pending, {"current": "2.145.6", "latest": "2.150.6"})

    def test_current_cli_yields_no_notice(self):
        self.write_version("2.150.6", "2.150.6")
        self.assertIsNone(sfx._pending_cli_update_cached())
        # A latest OLDER than current (stale cache) is likewise not pending.
        self.write_version("2.150.6", "2.145.6")
        self.assertIsNone(sfx._pending_cli_update_cached())

    def test_stale_cache_current_after_autoupdate_is_silent(self):
        # The reported bug: oclif rewrites the cache's `current` only on its own
        # throttled check, so right after an autoupdate it lags. Here the cache still
        # reads current=2.145.6 < latest=2.150.6, but the LIVE client is already at
        # 2.150.6 — the update happened. Detection must read the live client and stay
        # silent, not narrate the already-applied bump on every session forever.
        self.write_version("2.145.6", "2.150.6")
        self.write_client("2.150.6")
        self.assertIsNone(sfx._pending_cli_update_cached())

    def test_genuine_pending_update_reports_the_live_client_version(self):
        # A real pending bump: the live client (2.150.6) is behind latest (2.151.6).
        # The notice fires and its `current` is the live client version, not the
        # cache's stale field (2.140.0 here) — so the user sees the true starting point.
        self.write_version("2.140.0", "2.151.6")
        self.write_client("2.150.6")
        self.assertEqual(
            sfx._pending_cli_update_cached(), {"current": "2.150.6", "latest": "2.151.6"}
        )

    def test_live_client_version_read_without_subprocess(self):
        # Reading the installed version is filesystem-only (the shim's own layout) —
        # it must never shell out, keeping the PreToolUse hook latency-free.
        self.write_client("2.150.6")
        forbidden = AssertionError("installed-version read must not shell out")
        with mock.patch.object(sfx.subprocess, "run", side_effect=forbidden):
            self.assertEqual(sfx._installed_cli_client_version(), "2.150.6")

    def test_missing_cache_file_is_silent(self):
        self.assertIsNone(sfx._pending_cli_update_cached())

    def test_disabled_autoupdate_suppresses_notice(self):
        self.write_version("2.145.6", "2.150.6")
        for var in ("SF_DISABLE_AUTOUPDATE", "SFDX_DISABLE_AUTOUPDATE"):
            with self.subTest(var=var), mock.patch.dict(os.environ, {var: "true"}):
                self.assertIsNone(sfx._pending_cli_update_cached())

    def test_update_check_opt_out_suppresses_notice(self):
        self.write_version("2.145.6", "2.150.6")
        with mock.patch.dict(os.environ, {sfx._UPDATE_CHECK_ENV: "1"}):
            self.assertIsNone(sfx._pending_cli_update_cached())

    def test_malformed_cache_fails_open(self):
        (self.cache / "version").write_text("{ not json", encoding="utf-8")
        self.assertIsNone(sfx._pending_cli_update_cached())
        (self.cache / "version").write_text(json.dumps({"current": 1, "latest": 2}), encoding="utf-8")
        self.assertIsNone(sfx._pending_cli_update_cached())

    def test_version_values_are_sanitized(self):
        # A poisoned cache cannot inject control sequences onto the surface.
        self.write_version("2.145.6\x1b[31m", "2.150.6\n$(whoami)")
        pending = sfx._pending_cli_update_cached()
        self.assertNotIn("\x1b", pending["current"])
        self.assertNotIn("\n", pending["latest"])

    # --- PreToolUse advisory --------------------------------------------------

    def test_sf_command_with_pending_update_prints_one_short_line(self):
        self.write_version("2.145.6", "2.150.6")
        forbidden = AssertionError("the advisory must not shell out")
        with mock.patch.object(sfx.subprocess, "run", side_effect=forbidden):
            result = self.run_hook()
        self.assertTrue(result.get("continue"))  # never blocks the command
        visible = strip_ansi(result["systemMessage"])
        self.assertEqual(len(visible.splitlines()), 1)  # one succinct line
        self.assertIn("2.145.6", visible)
        self.assertIn("2.150.6", visible)
        self.assertIn("~1", visible)  # roughly time-bounded

    def test_notice_fires_at_most_once_per_session(self):
        self.write_version("2.145.6", "2.150.6")
        first = self.run_hook(command="sf --version")
        second = self.run_hook(command="sf org display")
        self.assertIn("systemMessage", first)
        self.assertNotIn("systemMessage", second)  # marker suppresses the repeat

    def test_current_cli_is_silent_and_adds_no_latency(self):
        # Acceptance criterion 2: CLI current → no message.
        self.write_version("2.150.6", "2.150.6")
        result = self.run_hook()
        self.assertTrue(result.get("continue"))
        self.assertNotIn("systemMessage", result)

    def test_non_sf_command_is_ignored(self):
        self.write_version("2.145.6", "2.150.6")
        result = self.run_hook(command="grep -r sf .")
        self.assertNotIn("systemMessage", result)

    def test_ui_mode_off_suppresses_the_visible_line(self):
        self.write_version("2.145.6", "2.150.6")
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_UI_MODE": "off"}):
            result = self.run_hook()
        self.assertTrue(result.get("continue"))
        self.assertNotIn("systemMessage", result)

    def test_session_start_never_carries_the_notice(self):
        # The whole point of the redesign: an ordinary session start — even with a
        # pending update in the cache — says nothing about the CLI update.
        self.write_version("2.145.6", "2.150.6")
        output = io.StringIO()
        payload = io.StringIO(json.dumps({"source": "startup", "session_id": "cs"}))
        with mock.patch.object(sfx.sys, "stdin", payload), redirect_stdout(output):
            self.assertEqual(sfx.cmd_detect(), 0)
        result = json.loads(output.getvalue())
        self.assertNotIn("systemMessage", result)
        self.assertNotIn("CLI update",
                         result.get("hookSpecificOutput", {}).get("additionalContext", ""))


if __name__ == "__main__":
    unittest.main()
