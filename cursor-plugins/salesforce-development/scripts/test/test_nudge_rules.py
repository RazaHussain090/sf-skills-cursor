#!/usr/bin/env python3
"""Unit proofs for the confidence-based nudge engine (nudge_rules).

Covers the selector contract (Gate 0, the strict ladder, tie-breaks, and the
full-list `journey hints` behavior) and a representative sample of the ship-first
rules. Rules are pure functions of NudgeInputs, so every case is built in-memory
with no filesystem or org."""
from __future__ import annotations

import unittest
from pathlib import Path

from _test_support import load_module

SCRIPTS = Path(__file__).resolve().parent.parent
nr = load_module(SCRIPTS / "nudge_rules.py", "nudge_rules_under_test")
sfx = load_module(SCRIPTS / "sf_context.py", "sf_context_for_nudge_sync")


class StageOrderSyncTests(unittest.TestCase):
    def test_stage_order_matches_sf_context(self):
        # The duplicated tuple must never drift from the canonical one.
        self.assertEqual(tuple(nr.STAGE_ORDER), tuple(sfx.JOURNEY_STAGES))

    def test_band_prefixes_match_sf_context(self):
        # sf_context duplicates the band-label prefixes for its per-line width
        # exemption (`_NUDGE_BAND_PREFIXES`) rather than loading the engine on that
        # hot path. This is the STAGE_ORDER-style drift guard that keeps the mirror
        # byte-identical to the single source of truth, `band_labels()` — including
        # the ⚠️ variation selector, an easy byte to lose in an editor.
        expected = tuple(f"{emoji} {label}: " for emoji, label in nr.band_labels())
        self.assertEqual(expected, sfx._NUDGE_BAND_PREFIXES)


class Gate0Tests(unittest.TestCase):
    def test_actionless_candidate_is_dropped(self):
        # A rule that emits a candidate with an empty action must never surface.
        @nr.rule
        def _actionless(_inputs):
            return nr.Candidate(
                id="test.actionless", stage="Build", severity=nr.SEV_BLOCKING,
                confidence=nr.CONFIDENCE_A, action="", message="no action",
                dedup_key="test.actionless",
            )

        try:
            inputs = nr.NudgeInputs(reached=frozenset({"Connect"}))
            self.assertNotIn("test.actionless", {c.id for c in nr.all_hints(inputs)})
            picked = nr.select(inputs)
            self.assertFalse(picked and picked.id == "test.actionless")
        finally:
            nr._RULES.remove(_actionless)


class LadderTests(unittest.TestCase):
    def test_no_org_wins_when_nothing_reached(self):
        picked = nr.select(nr.NudgeInputs())
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, "connect.no-org")

    def test_unreachable_no_longer_outranks_a_tier_a_gap(self):
        # journey-nudges Phase 8 reband: connect.unreachable dropped from SEV_BLOCKING
        # to SEV_RISK (a routine re-auth, not a blocker), so it no longer earns rung 1
        # / is_uncapped and no longer auto-wins. Connect is reached (target set), so on
        # a journey whose frontier has moved past it, unreachable is only a reached-stage
        # warning (rung 99 here — Connect isn't the frontier) and the Tier-A gap wins.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build"}),
            has_target=True, org_status="unreachable", org_alias="my-org",
            has_apex_classes=True, has_tests=False,
        )
        self.assertEqual(nr.select(inputs).id, "test.apex-no-tests")
        unreachable = nr.connect_unreachable(inputs)
        self.assertEqual(nr.band_label(unreachable), ("⚠️", "Heads up"))
        self.assertFalse(nr.is_uncapped(unreachable))

    def test_unreachable_still_renders_inline_when_connect_is_the_frontier(self):
        # Reband did not silence it: on a just-connected journey (Connect is the frontier,
        # nothing past it reached) an unreachable org is a frontier warning — rung 4,
        # inside the inline cutoff — it just no longer jumps the queue as a blocker.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect"}), has_target=True,
            org_status="unreachable", org_alias="my-org",
        )
        self.assertEqual(nr.select(inputs).id, "connect.unreachable")

    def test_unreachable_still_renders_inline_once_frontier_has_moved_on(self):
        # Finding 5: connect.unreachable is a live operational precondition, not a
        # one-time progress gap like project.no-git — the org doesn't become
        # reachable again just because the journey's frontier moved past Connect.
        # Before the rung-5 fix this fell to rung 99 (Connect reached, not frontier)
        # and `select` returned None even with nothing else to nudge on — an
        # unreachable org going completely unmentioned once the user built past it.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Test", "Deploy", "Observe"}),
            has_target=True, org_status="unreachable", org_alias="my-org",
            is_git_repo=True, has_source=True, has_tests=True, has_apex_classes=True,
            has_prior_deploy_success=True, any_test_event_ever=True,
        )
        picked = nr.select(inputs)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, "connect.unreachable")

    def test_tier_a_gap_beats_reached_stage_warning(self):
        # A Tier-A gap (no tests, Test unreached) outranks a frontier-adjacent
        # hygiene warning (no git on the reached Project stage).
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build"}),
            has_target=True, org_status="configured",
            has_apex_classes=True, has_tests=False,
            is_git_repo=False,
        )
        picked = nr.select(inputs)
        self.assertEqual(picked.id, "test.apex-no-tests")

    def test_all_hints_includes_non_inline_candidates(self):
        # The `journey hints` list surfaces everything actionable, even a rung-99
        # reached-stage warning that would never win inline.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Test", "Deploy", "Observe"}),
            has_target=True, org_status="configured", is_git_repo=False,
        )
        ids = {c.id for c in nr.all_hints(inputs)}
        self.assertIn("project.no-git", ids)

    def test_select_is_none_when_all_clear(self):
        # A fully-set-up, clean project with tests and a passing deploy: nothing to nudge.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Test", "Deploy", "Observe"}),
            has_target=True, org_status="reachable", is_git_repo=True,
            has_source=True, has_tests=True, has_apex_classes=True,
            has_prior_deploy_success=True, any_test_event_ever=True,
        )
        self.assertIsNone(nr.select(inputs))

    def test_just_scaffolded_surfaces_build_hint_on_scaffold_splash(self):
        # A real react/angular scaffold ships BOTH sample source AND a sample test file,
        # so the fresh project reaches Build *and* Test — making Build a reached,
        # non-frontier stage. That drops build.just-scaffolded to rung 99, so the plain
        # `select` ladder would leave the splash slot empty (its only other candidate,
        # deploy.never-deployed, is suppressed on just_scaffolded). `select_for_scaffold`
        # is the splash's selector: it keeps the same ladder but falls back to the
        # fresh-scaffold Build hint when the ladder is otherwise quiet.
        base = dict(
            reached=frozenset({"Connect", "Project", "Build", "Test"}),
            has_target=True, org_status="configured",
            has_source=True, has_tests=True, has_apex_classes=True,
            has_prior_deploy_success=False, project_template="reactexternalapp",
        )
        # Plain ladder is quiet on the fresh scaffold (deploy/test rules suppressed,
        # build hint is rung 99) — the empty-slot bug the scaffold selector fixes.
        self.assertIsNone(nr.select(nr.NudgeInputs(**base, just_scaffolded=True)))
        self.assertEqual(
            nr.select_for_scaffold(nr.NudgeInputs(**base, just_scaffolded=True)).id,
            "build.just-scaffolded",
        )

    def test_scaffold_selector_yields_to_earlier_gap_and_blocker(self):
        # `select_for_scaffold` stays holistic: the fresh-scaffold Build hint is only a
        # FALLBACK, so a genuine earlier-stage gap or a live blocker still wins — journey
        # hints reflect where the user actually is, not just "you scaffolded".
        base = dict(
            has_source=True, has_tests=True, project_template="reactexternalapp",
            just_scaffolded=True,
        )
        # Authed org but none set as default (Connect not reached) — connect an org first.
        gap = nr.NudgeInputs(
            reached=frozenset({"Project", "Build", "Test"}),
            has_target=False, has_authed_org=True, **base,
        )
        self.assertEqual(nr.select_for_scaffold(gap).id, "connect.no-default")
        # A live test failure is a rung-1 blocker — it must outrank the build hint.
        blocker = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Test"}),
            has_target=True, test_failed_unresolved=True, last_test_failed_ts=123.0, **base,
        )
        self.assertEqual(nr.select_for_scaffold(blocker).id, "test.failed-needs-fix")

    def test_scaffold_selector_suppresses_premature_boilerplate_nudges(self):
        # The Apex on a fresh scaffold is the template's sample code, not the user's, so
        # test.apex-no-tests and test.static-analysis-never-run must stay quiet on the
        # splash — the plain build hint carries it instead of "test/analyze the boilerplate".
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build"}),
            has_target=True, has_source=True, has_apex_classes=True, has_tests=False,
            has_code_analyzer_run_ever=False, project_template="agent", just_scaffolded=True,
        )
        self.assertIsNone(nr.test_apex_no_tests(inputs))
        self.assertIsNone(nr.test_static_analysis_never_run(inputs))
        self.assertEqual(nr.select_for_scaffold(inputs).id, "build.just-scaffolded")


class RuleTriggerTests(unittest.TestCase):
    def test_no_default_when_authed_but_no_target(self):
        picked = nr.select(nr.NudgeInputs(has_authed_org=True, has_target=False))
        self.assertEqual(picked.id, "connect.no-default")

    def test_empty_scaffold_when_project_but_no_source(self):
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project"}), has_target=True,
            org_status="configured", has_source=False,
        )
        ids = {c.id for c in nr.all_hints(inputs)}
        self.assertIn("build.empty-scaffold", ids)

    def test_destructive_manifest_is_actionable(self):
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build"}), has_target=True,
            org_status="configured", has_source=True, destructive_manifest_present=True,
        )
        hit = [c for c in nr.all_hints(inputs) if c.id == "deploy.destructive-manifest"]
        self.assertTrue(hit and hit[0].action)

    def test_deploy_unverified_uses_deploy_ts_for_recency(self):
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Deploy"}),
            has_target=True, org_status="reachable",
            has_source=True, has_prior_deploy_success=True, any_test_event_ever=True,
            deploy_unverified=True, last_deploy_passed_ts=123456.0,
        )
        hit = [c for c in nr.all_hints(inputs) if c.id == "observe.deploy-unverified"]
        self.assertTrue(hit)
        self.assertEqual(hit[0].evidence_ts, 123456.0)

    def test_confidence_is_always_a_or_b(self):
        # Sweep a permissive input so many rules fire; none may emit Tier-C.
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project"}), has_target=True,
            org_status="configured", has_apex_classes=True, is_git_repo=False,
            tracked_ignorable=True, destructive_manifest_present=True, has_source=True,
        )
        for c in nr.all_hints(inputs):
            self.assertIn(c.confidence, (nr.CONFIDENCE_A, nr.CONFIDENCE_B), c.id)


class PerRuleCoverageTests(unittest.TestCase):
    """Direct present/absent proof for every one of the 14 ship-first rules.

    Each rule is called directly (bypassing select/all_hints) so presence and
    absence are pinned independently of ladder/ranking behavior."""

    def test_connect_no_org(self):
        c = nr.connect_no_org(nr.NudgeInputs())
        self.assertEqual(c.id, "connect.no-org")
        self.assertIsNone(nr.connect_no_org(nr.NudgeInputs(has_target=True)))
        self.assertIsNone(nr.connect_no_org(nr.NudgeInputs(has_authed_org=True)))

    def test_connect_no_default(self):
        c = nr.connect_no_default(nr.NudgeInputs(has_authed_org=True, has_target=False))
        self.assertEqual(c.id, "connect.no-default")
        self.assertIsNone(nr.connect_no_default(nr.NudgeInputs(has_authed_org=True, has_target=True)))
        self.assertIsNone(nr.connect_no_default(nr.NudgeInputs(has_authed_org=False)))

    def test_connect_unreachable(self):
        c = nr.connect_unreachable(nr.NudgeInputs(org_status="unreachable", org_alias="my-org"))
        self.assertEqual(c.id, "connect.unreachable")
        # SEV_RISK, not blocking: an unreachable org is a routine re-auth (⚠️ Heads up),
        # not real work / data loss — see the rule's own note.
        self.assertEqual(c.severity, nr.SEV_RISK)
        self.assertIsNone(nr.connect_unreachable(nr.NudgeInputs(org_status="reachable")))
        self.assertIsNone(nr.connect_unreachable(nr.NudgeInputs(org_status="configured")))

    def test_connect_prod_for_dev(self):
        c = nr.connect_prod_for_dev(nr.NudgeInputs(is_production=True, org_status="reachable", org_alias="prod1"))
        self.assertEqual(c.id, "connect.prod-for-dev")
        self.assertIsNone(nr.connect_prod_for_dev(nr.NudgeInputs(is_production=False, org_status="reachable")))
        self.assertIsNone(nr.connect_prod_for_dev(nr.NudgeInputs(is_production=True, org_status="unreachable")))

    def test_connect_scratch_near_expiry(self):
        # journey-nudges Phase 6 (C5): the near-expiry runway, threshold-inclusive
        # at both ends (0 = expires today, 3 = the configured max lead time).
        c = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=3, org_alias="my-scratch"))
        self.assertEqual(c.id, "connect.scratch-near-expiry")
        self.assertEqual(c.severity, nr.SEV_RISK)
        self.assertEqual(c.confidence, nr.CONFIDENCE_A)
        self.assertTrue(c.action)
        self.assertIn("my-scratch", c.message)
        self.assertIn("3 days", c.message)
        c0 = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=0))
        self.assertIsNotNone(c0)
        self.assertIn("0 days", c0.message)
        c1 = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=1))
        self.assertIn("1 day", c1.message)  # singular, not "1 days"
        # Just past the threshold: not "near" enough yet.
        self.assertIsNone(nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=4)))
        # Comfortable runway: no nudge.
        self.assertIsNone(nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=30)))
        # Already past its date: a distinct, more urgent state with its own rule
        # (connect_scratch_past_expiry / connect_scratch_expired, below) — must NOT
        # also fire as "near expiry" (no double-fire across the three rules).
        self.assertIsNone(nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=-1)))
        # Not a scratch org / field never resolved: nothing to nudge on.
        self.assertIsNone(nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=None)))
        # Confirmed expired takes precedence even if days happens to be in the near
        # window (e.g. a stale/edge day count alongside a hard isExpired=True) —
        # connect_scratch_expired must be the one that fires, not this rule.
        self.assertIsNone(nr.connect_scratch_near_expiry(
            nr.NudgeInputs(scratch_expiry_days=1, is_scratch_expired=True)
        ))

    def test_connect_scratch_near_expiry_evidence_fp_tracks_the_day_count(self):
        # A changing day count re-surfaces (a genuinely new fact each day), but the
        # same day count for the same alias never re-nags within that day.
        a = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=2, org_alias="s1"))
        b = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=2, org_alias="s1"))
        c = nr.connect_scratch_near_expiry(nr.NudgeInputs(scratch_expiry_days=1, org_alias="s1"))
        self.assertEqual(a.evidence_fp, b.evidence_fp)
        self.assertNotEqual(a.evidence_fp, c.evidence_fp)

    def test_connect_scratch_past_expiry(self):
        # journey-nudges Phase 6 (C5 round 2): the urgent, not-yet-confirmed-dead
        # state — expirationDate has passed but isExpired is still False (verified
        # live: status stays "Active"). Silence here would misleadingly read as
        # "all fine," so this must fire.
        c = nr.connect_scratch_past_expiry(
            nr.NudgeInputs(scratch_expiry_days=-1, is_scratch_expired=False, org_alias="my-scratch")
        )
        self.assertEqual(c.id, "connect.scratch-past-expiry")
        self.assertEqual(c.severity, nr.SEV_RISK)
        self.assertEqual(c.confidence, nr.CONFIDENCE_A)
        self.assertTrue(c.action)
        self.assertIn("my-scratch", c.message)
        self.assertIn("1 day", c.message)
        self.assertIn("may already be", c.message.lower())
        # Boundary: day 0 (expires today) is the near-expiry rule's territory, not
        # this one — this rule is strictly negative days.
        self.assertIsNone(nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=0)))
        # Positive runway: nothing to nudge on here.
        self.assertIsNone(nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=3)))
        # Field never resolved: nothing to nudge on.
        self.assertIsNone(nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=None)))
        # Confirmed expired: connect_scratch_expired must win instead, even though
        # the day count would otherwise qualify.
        self.assertIsNone(nr.connect_scratch_past_expiry(
            nr.NudgeInputs(scratch_expiry_days=-5, is_scratch_expired=True)
        ))

    def test_connect_scratch_past_expiry_evidence_fp_tracks_the_day_count(self):
        # Each further day past expiry is a genuinely new fact (more overdue), so it
        # re-surfaces; the same day count for the same alias does not re-nag.
        a = nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=-2, org_alias="s1"))
        b = nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=-2, org_alias="s1"))
        c = nr.connect_scratch_past_expiry(nr.NudgeInputs(scratch_expiry_days=-3, org_alias="s1"))
        self.assertEqual(a.evidence_fp, b.evidence_fp)
        self.assertNotEqual(a.evidence_fp, c.evidence_fp)

    def test_connect_scratch_expired(self):
        # journey-nudges Phase 6 (C5 round 2): the CLI-confirmed-dead state. Fires on
        # isExpired alone, independent of the day count's sign — SEV_BLOCKING since
        # any command targeting this org will fail, parallel to connect_unreachable.
        c = nr.connect_scratch_expired(nr.NudgeInputs(is_scratch_expired=True, org_alias="my-scratch"))
        self.assertEqual(c.id, "connect.scratch-expired")
        self.assertEqual(c.severity, nr.SEV_BLOCKING)
        self.assertEqual(c.confidence, nr.CONFIDENCE_A)
        self.assertTrue(c.action)
        self.assertIn("my-scratch", c.message)
        self.assertTrue(nr.is_uncapped(c))
        self.assertIsNone(nr.connect_scratch_expired(nr.NudgeInputs(is_scratch_expired=False)))
        # Fires regardless of what the (now largely moot) day count says.
        c_pos = nr.connect_scratch_expired(nr.NudgeInputs(is_scratch_expired=True, scratch_expiry_days=5))
        self.assertIsNotNone(c_pos)

    def test_connect_scratch_expired_evidence_fp_does_not_re_key_on_day_count(self):
        # Unlike the two date-math rules, this one is fingerprinted on the alias
        # alone (mirrors connect_unreachable/connect_prod_for_dev) — a confirmed-
        # expired org doesn't get "more expired" day over day, so the fingerprint
        # gate should hold across day-count churn, preventing re-nag.
        a = nr.connect_scratch_expired(nr.NudgeInputs(is_scratch_expired=True, org_alias="s1", scratch_expiry_days=-1))
        b = nr.connect_scratch_expired(nr.NudgeInputs(is_scratch_expired=True, org_alias="s1", scratch_expiry_days=-9))
        self.assertEqual(a.evidence_fp, b.evidence_fp)

    def test_scratch_expiry_rules_are_mutually_exclusive_across_states(self):
        # Exactly one of the three scratch-expiry candidates ever fires for a given
        # (days, isExpired) combination, including the co-occurrence edge case where
        # a negative day count coincides with a confirmed isExpired=True.
        scratch_ids = {"connect.scratch-near-expiry", "connect.scratch-past-expiry", "connect.scratch-expired"}
        cases = [
            (3, False), (0, False), (1, False),  # near-expiry window
            (-1, False), (-10, False),            # past-active window
            (-1, True), (5, True), (None, True),  # confirmed expired, any day count
        ]
        for days, expired in cases:
            inputs = nr.NudgeInputs(
                scratch_expiry_days=days, is_scratch_expired=expired, org_alias="my-scratch",
            )
            fired = [c.id for c in nr.all_hints(inputs) if c.id in scratch_ids]
            self.assertEqual(len(fired), 1, f"days={days} expired={expired} -> {fired}")

    def test_project_no_git(self):
        c = nr.project_no_git(nr.NudgeInputs(reached=frozenset({"Project"}), is_git_repo=False))
        self.assertEqual(c.id, "project.no-git")
        self.assertIsNone(nr.project_no_git(nr.NudgeInputs(reached=frozenset(), is_git_repo=False)))
        self.assertIsNone(nr.project_no_git(nr.NudgeInputs(reached=frozenset({"Project"}), is_git_repo=True)))

    def test_project_tracked_ignorable(self):
        c = nr.project_tracked_ignorable(
            nr.NudgeInputs(reached=frozenset({"Project"}), tracked_ignorable=True)
        )
        self.assertEqual(c.id, "project.tracked-ignorable")
        # Tagged hygiene so it resolves to the ✨ Tidy band, not 🚀 Try next.
        self.assertEqual(c.kind, nr.HYGIENE_KIND)
        self.assertIsNone(
            nr.project_tracked_ignorable(
                nr.NudgeInputs(reached=frozenset({"Project"}), tracked_ignorable=False)
            )
        )
        # Gated on Project like its sibling project_no_git: never fires outside a
        # Salesforce project, even in a plain git repo that tracks .sfdx/node_modules.
        self.assertIsNone(
            nr.project_tracked_ignorable(
                nr.NudgeInputs(reached=frozenset(), tracked_ignorable=True)
            )
        )

    def test_build_empty_scaffold(self):
        c = nr.build_empty_scaffold(nr.NudgeInputs(reached=frozenset({"Project"}), has_source=False))
        self.assertEqual(c.id, "build.empty-scaffold")
        # Message is the situation only — the "generate your first component" call to
        # action lives in `action`, so the rendered `<message> — <action>` line no
        # longer says it twice (journey-nudges Phase 8 copy fix).
        self.assertEqual(c.message, "Project has no local source yet.")
        self.assertNotIn("generate", c.message)
        # A momentum nudge, not hygiene — resolves to 🚀 Try next.
        self.assertEqual(c.kind, "")
        self.assertIsNone(nr.build_empty_scaffold(nr.NudgeInputs(reached=frozenset({"Project"}), has_source=True)))
        self.assertIsNone(nr.build_empty_scaffold(nr.NudgeInputs(reached=frozenset(), has_source=False)))

    def test_build_empty_scaffold_action_varies_by_template(self):
        # The action is looked up by creation template; the dedup_key stays static
        # across every variant — this is a presentation-only change (Phase 8 follow-up).
        fallback = "generate a component (Apex, Agent, Analytics or UI Bundle)"
        expected_by_template = {
            "standard": "generate a component (Apex class, LWC, or Flow)",
            "analytics": "generate a CRM Analytics app or dashboard",
            "agent": "add a topic, action, or Apex class to your agent",
            "reactinternalapp": "generate a React or Angular UI bundle",
            "reactexternalapp": "generate a React or Angular UI bundle",
            "angularinternalapp": "generate a React or Angular UI bundle",
            "angularexternalapp": "generate a React or Angular UI bundle",
            "empty": fallback,
            None: fallback,
            "bogus": fallback,
        }
        for template, expected_action in expected_by_template.items():
            c = nr.build_empty_scaffold(
                nr.NudgeInputs(reached=frozenset({"Project"}), has_source=False, project_template=template)
            )
            self.assertEqual(c.action, expected_action, msg=f"template={template!r}")
            self.assertEqual(c.dedup_key, "build.empty-scaffold", msg=f"template={template!r}")

    def test_test_apex_no_tests(self):
        c = nr.test_apex_no_tests(nr.NudgeInputs(has_apex_classes=True, has_tests=False))
        self.assertEqual(c.id, "test.apex-no-tests")
        self.assertIsNone(nr.test_apex_no_tests(nr.NudgeInputs(has_apex_classes=True, has_tests=True)))
        self.assertIsNone(nr.test_apex_no_tests(nr.NudgeInputs(has_apex_classes=False)))

    def test_test_deploy_no_test_ever(self):
        c = nr.test_deploy_no_test_ever(
            nr.NudgeInputs(has_prior_deploy_success=True, any_test_event_ever=False)
        )
        self.assertEqual(c.id, "test.deploy-no-test-ever")
        self.assertIsNone(nr.test_deploy_no_test_ever(
            nr.NudgeInputs(has_prior_deploy_success=True, any_test_event_ever=True)
        ))
        self.assertIsNone(nr.test_deploy_no_test_ever(nr.NudgeInputs(has_prior_deploy_success=False)))

    def test_deploy_never_deployed(self):
        c = nr.deploy_never_deployed(nr.NudgeInputs(has_source=True, has_prior_deploy_success=False))
        self.assertEqual(c.id, "deploy.never-deployed")
        self.assertIsNone(nr.deploy_never_deployed(
            nr.NudgeInputs(has_source=True, has_prior_deploy_success=True)
        ))
        self.assertIsNone(nr.deploy_never_deployed(nr.NudgeInputs(has_source=False)))
        # Suppressed on a just-scaffolded project: its "source" is untouched template
        # boilerplate, so "deploy it" is premature — build.just-scaffolded wins instead.
        self.assertIsNone(nr.deploy_never_deployed(
            nr.NudgeInputs(has_source=True, has_prior_deploy_success=False, just_scaffolded=True)
        ))

    def test_build_just_scaffolded(self):
        # Fires only for the has_source complement of build_empty_scaffold, and only
        # on the scaffold splash (just_scaffolded=True).
        c = nr.build_just_scaffolded(
            nr.NudgeInputs(reached=frozenset({"Project", "Build"}), has_source=True, just_scaffolded=True)
        )
        self.assertEqual(c.id, "build.just-scaffolded")
        self.assertEqual(c.stage, "Build")
        self.assertEqual(c.message, "Project just scaffolded — start building.")
        # A momentum nudge, not hygiene — resolves to 🚀 Try next.
        self.assertEqual(c.kind, "")
        # Off unless BOTH just_scaffolded AND has_source hold.
        self.assertIsNone(nr.build_just_scaffolded(
            nr.NudgeInputs(has_source=True, just_scaffolded=False)
        ))
        self.assertIsNone(nr.build_just_scaffolded(
            nr.NudgeInputs(has_source=False, just_scaffolded=True)
        ))

    def test_build_just_scaffolded_action_varies_by_template(self):
        fallback = "generate a component (Apex, Agent, Analytics or UI Bundle)"
        expected_by_template = {
            "agent": "add a topic, action, or Apex class to your agent",
            "reactinternalapp": "install npm deps, then build out your app",
            "reactexternalapp": "install npm deps, then build out your app",
            "angularinternalapp": "install npm deps, then build out your app",
            "angularexternalapp": "install npm deps, then build out your app",
            "standard": fallback,   # a standard scaffold never ships source, so it never
            None: fallback,         # reaches this rule — but the lookup still falls back cleanly.
            "bogus": fallback,
        }
        for template, expected_action in expected_by_template.items():
            c = nr.build_just_scaffolded(
                nr.NudgeInputs(has_source=True, just_scaffolded=True, project_template=template)
            )
            self.assertEqual(c.action, expected_action, msg=f"template={template!r}")
            self.assertEqual(c.dedup_key, "build.just-scaffolded", msg=f"template={template!r}")

    def test_deploy_uncommitted_in_pkg(self):
        c = nr.deploy_uncommitted_in_pkg(
            nr.NudgeInputs(dirty_paths_in_pkg_roots=3, has_prior_deploy_success=True)
        )
        self.assertEqual(c.id, "deploy.uncommitted-in-pkg")
        self.assertIsNone(nr.deploy_uncommitted_in_pkg(
            nr.NudgeInputs(dirty_paths_in_pkg_roots=0, has_prior_deploy_success=True)
        ))
        self.assertIsNone(nr.deploy_uncommitted_in_pkg(
            nr.NudgeInputs(dirty_paths_in_pkg_roots=3, has_prior_deploy_success=False)
        ))

    def test_deploy_destructive_manifest(self):
        c = nr.deploy_destructive_manifest(nr.NudgeInputs(destructive_manifest_present=True))
        self.assertEqual(c.id, "deploy.destructive-manifest")
        self.assertIsNone(nr.deploy_destructive_manifest(nr.NudgeInputs(destructive_manifest_present=False)))

    def test_observe_deploy_unverified(self):
        c = nr.observe_deploy_unverified(nr.NudgeInputs(deploy_unverified=True))
        self.assertEqual(c.id, "observe.deploy-unverified")
        self.assertIsNone(nr.observe_deploy_unverified(nr.NudgeInputs(deploy_unverified=False)))

    def test_test_failed_needs_fix(self):
        # journey-nudges Phase 6 (T7/O3): fires only on an unresolved test failure,
        # at SEV_BLOCKING (rung 1, uncapped) since a failing test is actively broken.
        c = nr.test_failed_needs_fix(
            nr.NudgeInputs(test_failed_unresolved=True, last_test_failed_ts=999.0)
        )
        self.assertEqual(c.id, "test.failed-needs-fix")
        self.assertEqual(c.severity, nr.SEV_BLOCKING)
        self.assertEqual(c.confidence, nr.CONFIDENCE_B)
        self.assertTrue(c.action)
        self.assertEqual(c.evidence_ts, 999.0)
        self.assertIsNone(nr.test_failed_needs_fix(nr.NudgeInputs(test_failed_unresolved=False)))

    def test_test_static_analysis_never_run(self):
        # journey-nudges Phase 6 (T6): fires only when Apex exists on disk AND no
        # code-analyzer run has ever been recorded.
        c = nr.test_static_analysis_never_run(
            nr.NudgeInputs(has_apex_classes=True, has_code_analyzer_run_ever=False)
        )
        self.assertEqual(c.id, "test.static-analysis-never-run")
        self.assertEqual(c.confidence, nr.CONFIDENCE_B)
        self.assertTrue(c.action)
        # Tagged hygiene so it resolves to the ✨ Tidy band, not 🚀 Try next.
        self.assertEqual(c.kind, nr.HYGIENE_KIND)
        self.assertIsNone(nr.test_static_analysis_never_run(
            nr.NudgeInputs(has_apex_classes=True, has_code_analyzer_run_ever=True)
        ))
        self.assertIsNone(nr.test_static_analysis_never_run(
            nr.NudgeInputs(has_apex_classes=False, has_code_analyzer_run_ever=False)
        ))


class IsUncappedTests(unittest.TestCase):
    """`is_uncapped` is the pure predicate `sf_context`'s anti-nag session cap
    (journey-nudges Phase 4) calls to let a rung-1 blocking candidate bypass the
    cap. It must mirror `_rung`'s own rung-1 test exactly (severity >= SEV_BLOCKING
    at Tier-A/B confidence) so the two can never drift."""

    def test_none_candidate_is_not_uncapped(self):
        self.assertFalse(nr.is_uncapped(None))

    def test_blocking_severity_at_tier_a_is_uncapped(self):
        # A genuine remaining Fix-band blocker (an expired scratch org can't be revived —
        # real work). connect.unreachable is deliberately NOT one anymore (reband to
        # SEV_RISK), so this uses connect.scratch-expired instead.
        c = nr.Candidate(
            id="connect.scratch-expired", stage="Connect", severity=nr.SEV_BLOCKING,
            confidence=nr.CONFIDENCE_A, action="dx-org-manage  (recreate)",
            message="Scratch org is confirmed expired.", dedup_key="connect.scratch-expired",
        )
        self.assertTrue(nr.is_uncapped(c))

    def test_blocking_severity_at_tier_b_is_also_uncapped(self):
        # is_uncapped's confidence check is an "A or B" set, not a hardcoded A —
        # a durable, hook-proven Tier-B blocker earns the same bypass.
        c = nr.Candidate(
            id="test.blocking-b", stage="Test", severity=nr.SEV_BLOCKING,
            confidence=nr.CONFIDENCE_B, action="sf apex run test",
            message="A tracked blocker.", dedup_key="test.blocking-b",
        )
        self.assertTrue(nr.is_uncapped(c))

    def test_below_blocking_severity_is_capped(self):
        c = nr.Candidate(
            id="project.no-git", stage="Project", severity=nr.SEV_RISK,
            confidence=nr.CONFIDENCE_A, action="git init",
            message="Not a git repo.", dedup_key="project.no-git",
        )
        self.assertFalse(nr.is_uncapped(c))

    def test_blocking_severity_without_a_or_b_confidence_is_capped(self):
        # Defends the "mirrors rung 1 exactly" contract against a hypothetical
        # future confidence tier: blocking severity alone must never be enough.
        c = nr.Candidate(
            id="test.unknown-tier", stage="Test", severity=nr.SEV_BLOCKING,
            confidence="C", action="do something",
            message="Unrepresentable tier.", dedup_key="test.unknown-tier",
        )
        self.assertFalse(nr.is_uncapped(c))


class BandLabelTests(unittest.TestCase):
    """`band_label` is the pure, presentation-only mapping from a candidate's
    severity (plus the `hygiene` sub-kind) to the graded (emoji, label) both visible
    renderers lead a nudge with (journey-nudges Phase 8). Every band is exercised,
    including the softest-band catch-all for SEV_OPTIONAL and any unrecognized
    severity, so a future or malformed value can never crash a render."""

    def _c(self, severity, kind=""):
        return nr.Candidate(
            id="x", stage="Build", severity=severity, confidence=nr.CONFIDENCE_A,
            action="do it", message="a thing", dedup_key="x", kind=kind,
        )

    def test_blocking_is_fix(self):
        self.assertEqual(nr.band_label(self._c(nr.SEV_BLOCKING)), ("❌", "Fix"))

    def test_risk_is_heads_up(self):
        self.assertEqual(nr.band_label(self._c(nr.SEV_RISK)), ("⚠️", "Heads up"))

    def test_routine_non_hygiene_is_try_next(self):
        self.assertEqual(nr.band_label(self._c(nr.SEV_ROUTINE)), ("🚀", "Try next"))

    def test_routine_hygiene_is_tidy(self):
        # The hygiene sub-kind is what splits Tidy out of the momentum band: same
        # SEV_ROUTINE severity, different band.
        self.assertEqual(
            nr.band_label(self._c(nr.SEV_ROUTINE, kind=nr.HYGIENE_KIND)), ("✨", "Tidy"))

    def test_optional_is_tidy(self):
        self.assertEqual(nr.band_label(self._c(nr.SEV_OPTIONAL)), ("✨", "Tidy"))

    def test_unknown_low_severity_falls_to_tidy(self):
        # Catch-all: an unrepresentable low/negative severity resolves to the softest
        # band rather than raising.
        self.assertEqual(nr.band_label(self._c(-1)), ("✨", "Tidy"))

    def test_escalated_high_severity_stays_fix(self):
        # A hypothetical future band above SEV_BLOCKING stays loudest, never silently
        # softened.
        self.assertEqual(nr.band_label(self._c(nr.SEV_BLOCKING + 5)), ("❌", "Fix"))

    def test_hygiene_only_matters_at_routine(self):
        # `kind` is a ROUTINE-only discriminator: a hygiene tag on a higher band does
        # not pull it down to Tidy.
        self.assertEqual(
            nr.band_label(self._c(nr.SEV_RISK, kind=nr.HYGIENE_KIND)), ("⚠️", "Heads up"))

    def test_every_shipping_rule_resolves_to_a_known_band(self):
        # Exhaustive over the real rule set: each rule's own candidate must map to one
        # of the four declared bands (no rule can silently produce an off-taxonomy
        # label). Built with maximal inputs so as many rules as possible emit.
        bands = set(nr.band_labels())
        inputs = nr.NudgeInputs(
            reached=frozenset({"Connect", "Project", "Build", "Test", "Deploy"}),
            has_target=True, org_status="unreachable", org_alias="my-org",
            has_apex_classes=True, has_tests=False, is_git_repo=False,
            tracked_ignorable=True, has_source=True, has_prior_deploy_success=False,
            destructive_manifest_present=True,
        )
        seen = [nr.band_label(c) for c in nr.all_hints(inputs)]
        self.assertTrue(seen, "expected at least one candidate to exercise")
        for band in seen:
            self.assertIn(band, bands)

    def test_band_word_is_the_emoji_free_label_half(self):
        # `band_word` is the plain-text accessor the semantic-plain / compact ambient
        # surface consumes (journey-nudges Phase 8) — emoji-free but still the SAME
        # taxonomy. It must be exactly `band_label`'s label component, never a second
        # word list, so the two can't drift.
        for severity, kind in (
            (nr.SEV_BLOCKING, ""), (nr.SEV_RISK, ""), (nr.SEV_ROUTINE, ""),
            (nr.SEV_ROUTINE, nr.HYGIENE_KIND), (nr.SEV_OPTIONAL, ""), (-1, ""),
            (nr.SEV_BLOCKING + 5, ""),
        ):
            c = self._c(severity, kind=kind)
            self.assertEqual(nr.band_word(c), nr.band_label(c)[1])

    def test_band_words_is_the_closed_word_set_in_band_labels_order(self):
        # The words-only view of the taxonomy, guarding against a divergent second list.
        self.assertEqual(
            nr.band_words(), tuple(label for _emoji, label in nr.band_labels()))
        self.assertEqual(nr.band_words(), ("Fix", "Heads up", "Try next", "Tidy"))

    def test_band_word_carries_no_emoji(self):
        # The semantic-plain surface strips emoji entirely — the accessor must never
        # leak one back in.
        for word in nr.band_words():
            self.assertNotRegex(word, r"[❌⚠🚀✨]")


class ExceptionIsolationTests(unittest.TestCase):
    def test_raising_rule_is_skipped_others_survive(self):
        # One misbehaving rule must not take down the render — mirrors the
        # Gate0Tests cleanup pattern (register, assert, always remove).
        @nr.rule
        def _boom(_inputs):
            raise RuntimeError("boom")

        try:
            inputs = nr.NudgeInputs()  # connect.no-org still qualifies
            picked = nr.select(inputs)
            self.assertIsNotNone(picked)
            self.assertEqual(picked.id, "connect.no-org")
            ids = {c.id for c in nr.all_hints(inputs)}
            self.assertIn("connect.no-org", ids)
        finally:
            nr._RULES.remove(_boom)


if __name__ == "__main__":
    unittest.main()
