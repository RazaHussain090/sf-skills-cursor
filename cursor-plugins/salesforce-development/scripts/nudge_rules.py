#!/usr/bin/env python3
"""Confidence-based ALM nudge rules — the engine that replaces the journey rail.

The journey rail painted a linear six-stage progress bar. Dev is not linear, and
several stages lit on thin evidence. This module instead answers "what's next?":
given cheap, network-free facts already resolved by ``sf_context``, each rule may
emit ONE actionable nudge; a selector ranks them and the caller renders either the
single best one (inline, where the rail used to paint) or the full ranked list
(the ``journey hints`` command).

Design invariants (see .context/design-plans/journey-nudges-plan.md):

* PURE. Rules are functions of a frozen :class:`NudgeInputs` and nothing else — no
  I/O, no import of ``sf_context``. ``sf_context`` owns every read and hands the
  facts in, so there is no import cycle and every rule is unit-testable in isolation.
* USEFUL AND ACTIONABLE (Gate 0). A candidate with no concrete ``action`` is dropped
  before ranking. "Nothing you can do about it" is never a nudge.
* CONFIDENCE FLOOR. A rule may emit only Tier-A (a live filesystem/org fact) or
  Tier-B (a durable, hook-proven phase-tracker event) evidence. Tier-C activity (a
  skill merely dispatched) can never seed a visible nudge, so this module has no
  path to construct one.
* STRICT LADDER, not a weighted score — so a pile of small signals can never
  outvote one real blocker.

Note: this module intentionally omits ``from __future__ import annotations``. Its
frozen dataclasses are loaded by absolute path in unit tests (the sibling-loader
pattern), which does not register the module in ``sys.modules``; under PEP 563
string annotations, ``dataclasses`` on Python 3.13 then fails to resolve the module
namespace while scanning for ``KW_ONLY``. Real (non-string) annotations sidestep it,
and this module has no forward references that would need deferral.
"""
from dataclasses import dataclass
from typing import Callable, Optional

# Kept in lockstep with sf_context.JOURNEY_STAGES; a test asserts equality so the
# two never drift. Duplicated (not imported) so rules stay free of sf_context.
STAGE_ORDER: tuple[str, ...] = ("Connect", "Project", "Build", "Test", "Deploy", "Observe")

# Confidence tiers a rule may emit. Tier-C is deliberately unrepresentable here.
CONFIDENCE_A = "A"  # a live filesystem / org fact
CONFIDENCE_B = "B"  # a durable, hook-proven phase-tracker event

# Severity bands (drives rung 1 and the primary tie-break). Calibration is expected
# to iterate; the structure, not the exact numbers, is what this phase pins down.
SEV_OPTIONAL = 0   # nice-to-have hygiene
SEV_ROUTINE = 1    # the ordinary next step
SEV_RISK = 2       # an important gap or a risk worth naming
SEV_BLOCKING = 3   # actively broken — a command the user needs will fail


@dataclass(frozen=True)
class Candidate:
    """One nudge a rule wants to offer. ``action`` is required (Gate 0)."""

    id: str
    stage: str
    severity: int
    confidence: str
    action: str
    message: str
    dedup_key: str
    evidence_ts: float = 0.0
    evidence_fp: str = ""
    kind: str = ""          # presentation sub-kind within a severity band. Only
                            # "hygiene" is meaningful today: it splits the ✨ Tidy
                            # band out of the 🚀 Try-next momentum band, both of which
                            # sit at SEV_ROUTINE (see `band_label`). Presentation-only —
                            # never enters dedup_key/evidence_fp or the selection ladder.


@dataclass(frozen=True)
class NudgeInputs:
    """Every fact the rules read, pre-resolved by ``sf_context`` (network-free).

    All fields default to a benign "nothing known" so partial callers (a deploy
    hook that only knows deploy facts) and tests can build minimal inputs.
    """

    reached: frozenset = frozenset()          # stages with their own evidence
    # --- Connect / org ---
    org_status: str = "unknown"               # reachable/unreachable/configured/not-configured/unknown
    org_alias: Optional[str] = None
    is_production: bool = False
    is_scratch_or_sandbox: bool = False
    scratch_expiry_days: Optional[int] = None
    is_scratch_expired: bool = False          # `sf org list`'s scratchOrgs[].isExpired — a
                                               # separate, harder signal than the date math
                                               # above; a scratch org can sit past its
                                               # expirationDate for a while with this still
                                               # False (still Active, just on borrowed time)
    has_authed_org: bool = False
    has_target: bool = False
    # --- source / project ---
    has_source: bool = False
    just_scaffolded: bool = False             # this render IS the immediate post-scaffold
                                               # splash (cmd_scaffold_paint) — never set on any
                                               # other surface. It reinterprets has_source: on a
                                               # just-scaffolded project the "source" is untouched
                                               # template boilerplate, so this biases the ladder
                                               # toward a Build "start building" nudge
                                               # (build_just_scaffolded) and gates off the premature
                                               # deploy_never_deployed. Transient by design.
    has_tests: bool = False
    has_apex_classes: bool = False
    has_lwc: bool = False
    project_template: Optional[str] = None    # sfdx-project.json top-level `template`
                                               # (creation template id), if the producer wrote one
    is_git_repo: bool = True                  # default True: absence is the notable case
    dirty_paths_in_pkg_roots: int = 0
    tracked_ignorable: bool = False           # .sf/.sfdx/node_modules under version control
    destructive_manifest_present: bool = False
    source_api_version: Optional[str] = None
    cli_default_api_version: Optional[str] = None
    # --- deploy / test / observe (durable tracker) ---
    has_prior_deploy_success: bool = False
    any_test_event_ever: bool = False
    last_deploy_passed_ts: Optional[float] = None
    last_test_passed_ts: Optional[float] = None
    deploy_unverified: bool = False           # passed deploy, no later Observe for this org
    # --- second-wave writers (Phase 6) ---
    test_failed_unresolved: bool = False      # a Test/failed record with no later Test/passed
    last_test_failed_ts: Optional[float] = None
    has_code_analyzer_run_ever: bool = False  # Tier-C "ran once" activity, unscoped to an org


# The rule registry. Each entry is a pure NudgeInputs -> Optional[Candidate].
_RULES: list[Callable[[NudgeInputs], Optional[Candidate]]] = []


def rule(fn: Callable[[NudgeInputs], Optional[Candidate]]) -> Callable[[NudgeInputs], Optional[Candidate]]:
    """Register a rule. Rules never raise on missing facts — they return None."""
    _RULES.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# Connect / org lifecycle
# --------------------------------------------------------------------------- #
@rule
def connect_no_org(i: NudgeInputs) -> Optional[Candidate]:
    if i.has_target or i.has_authed_org:
        return None
    return Candidate(
        id="connect.no-org", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="sf org login web --set-default",
        message="No org connected yet — connect one to work against real data.",
        dedup_key="connect.no-org",
    )


@rule
def connect_no_default(i: NudgeInputs) -> Optional[Candidate]:
    if i.has_target or not i.has_authed_org:
        return None
    return Candidate(
        id="connect.no-default", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="sf config set target-org=<alias>  (see: sf org list)",
        message="Authenticated org(s) exist, but none is set as the default target.",
        dedup_key="connect.no-default",
    )


@rule
def connect_unreachable(i: NudgeInputs) -> Optional[Candidate]:
    # SEV_RISK, not SEV_BLOCKING: an unreachable target org is overwhelmingly just an
    # expired auth token — a routine `sf org login` re-auth, not broken work or data
    # loss. That's ⚠️ Heads up, not ❌ Fix. It lands at rung 2 (unreached Connect,
    # Tier-A), still inside the inline cutoff, but is intentionally NOT is_uncapped and
    # no longer auto-outranks a true blocker: the CLI itself shouts when a command hits
    # the unreachable org, so this nudge is advisory. The strictly-blocking Fix band is
    # reserved for connect.scratch-expired and test.failed-needs-fix (real work needed).
    if i.org_status != "unreachable":
        return None
    alias = i.org_alias or "<alias>"
    return Candidate(
        id="connect.unreachable", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action=f"sf org login web -o {alias}",
        message=f"Target org {alias} looks unreachable — auth may have expired.",
        dedup_key="connect.unreachable", evidence_fp=alias,
    )


@rule
def connect_prod_for_dev(i: NudgeInputs) -> Optional[Candidate]:
    if not i.is_production or i.org_status not in ("reachable", "configured"):
        return None
    alias = i.org_alias or "<alias>"
    return Candidate(
        id="connect.prod-for-dev", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="sf config set target-org=<sandbox-or-scratch>",
        message=f"Org {alias} is Production — use a sandbox or scratch org for dev work.",
        dedup_key="connect.prod-for-dev", evidence_fp=alias,
    )


# "Near expiry" runway (design catalog C5). Scratch orgs default to a 7-day life
# (max 30, per `sf org create scratch --duration-days`) and there is no in-place
# extension — the only fix is recreating before the clock runs out. 3 days is a
# short, concrete lead time to do that without nagging for the org's entire life
# (a wider window would start firing on day one of a 7-day default org).
_SCRATCH_NEAR_EXPIRY_DAYS = 3


@rule
def connect_scratch_near_expiry(i: NudgeInputs) -> Optional[Candidate]:
    # Tier-A: a live org fact (`sf org list`'s scratchOrgs[].expirationDate, date-
    # parsed by sf_context._scratch_expiry_days). A NEGATIVE count (date already
    # passed) and a confirmed `is_scratch_expired` are both excluded here, not just
    # outside the "near" window — those are distinct, more urgent states with their
    # own dedicated rules below (`connect_scratch_past_expiry`, `connect_scratch_
    # expired`), so this rule stays scoped to the pre-expiry runway only and none of
    # the three can double-fire for the same org. The actionable moment here is the
    # runway before expiry, day 0 included (expires today), not after.
    if i.is_scratch_expired or i.scratch_expiry_days is None or not (
        0 <= i.scratch_expiry_days <= _SCRATCH_NEAR_EXPIRY_DAYS
    ):
        return None
    alias = i.org_alias or "<alias>"
    days = i.scratch_expiry_days
    unit = "day" if days == 1 else "days"
    return Candidate(
        id="connect.scratch-near-expiry", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="dx-org-manage  (recreate — no in-place extension; only --duration-days at creation)",
        message=f"Scratch org {alias} expires in {days} {unit} — recreate it before then to avoid losing work.",
        dedup_key="connect.scratch-near-expiry", evidence_fp=f"{alias}:{days}",
    )


@rule
def connect_scratch_past_expiry(i: NudgeInputs) -> Optional[Candidate]:
    # The urgent, not-yet-confirmed-dead state (journey-nudges Phase 6, C5 round 2):
    # `expirationDate` has passed but the CLI has NOT confirmed the org expired
    # (`isExpired` False, `status` still "Active" per the live-verified shape). This
    # is the single most time-sensitive scratch-org state — it can vanish at any
    # moment — so silence here is actively misleading, not neutral. Gated OUT when
    # `is_scratch_expired` is True so `connect_scratch_expired` (below) always wins
    # once the CLI confirms it; the two dedup keys are distinct so they can never
    # double-fire for the same org.
    if i.scratch_expiry_days is None or i.scratch_expiry_days >= 0 or i.is_scratch_expired:
        return None
    alias = i.org_alias or "<alias>"
    days = -i.scratch_expiry_days
    unit = "day" if days == 1 else "days"
    return Candidate(
        id="connect.scratch-past-expiry", stage="Connect", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="dx-org-manage  (verify with sf org display, or recreate — no in-place extension; only --duration-days at creation)",
        message=(
            f"Scratch org {alias} is {days} {unit} past expiry and may already be "
            "gone — verify with sf org display or recreate before losing work."
        ),
        dedup_key="connect.scratch-past-expiry", evidence_fp=f"{alias}:{days}",
    )


@rule
def connect_scratch_expired(i: NudgeInputs) -> Optional[Candidate]:
    # The confirmed-dead state: `isExpired` True means the CLI itself has confirmed
    # the org is gone, independent of the day count's sign (a scratch org can be
    # confirmed expired the moment its date passes, or well after — the flag, not
    # the arithmetic, is authoritative here). SEV_BLOCKING, parallel to
    # `connect_unreachable`: any command targeting this org will fail, exactly the
    # "actively broken" bar that severity band documents. Rung 1 / uncapped (see
    # `is_uncapped`) and fingerprint-gated on the alias alone — like
    # `connect_unreachable`/`connect_prod_for_dev`, not the day count, since a
    # confirmed-expired org doesn't get "more expired" day over day — so this never
    # re-nags once shown, mirroring `test_failed_needs_fix`'s non-decaying, always-
    # uncapped precedent for a rung-1 blocker.
    if not i.is_scratch_expired:
        return None
    alias = i.org_alias or "<alias>"
    return Candidate(
        id="connect.scratch-expired", stage="Connect", severity=SEV_BLOCKING, confidence=CONFIDENCE_A,
        action="dx-org-manage  (recreate — expired scratch orgs can't be revived)",
        message=f"Scratch org {alias} is confirmed expired — commands against it will fail. Recreate it.",
        dedup_key="connect.scratch-expired", evidence_fp=alias,
    )


# --------------------------------------------------------------------------- #
# Project / source hygiene
# --------------------------------------------------------------------------- #
@rule
def project_no_git(i: NudgeInputs) -> Optional[Candidate]:
    if "Project" not in i.reached or i.is_git_repo:
        return None
    return Candidate(
        id="project.no-git", stage="Project", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="git init  (add a .gitignore)",
        message="This project isn't under version control — initialize git before you lose work.",
        dedup_key="project.no-git",
    )


@rule
def project_tracked_ignorable(i: NudgeInputs) -> Optional[Candidate]:
    if "Project" not in i.reached or not i.tracked_ignorable:
        return None
    return Candidate(
        id="project.tracked-ignorable", stage="Project", severity=SEV_ROUTINE, confidence=CONFIDENCE_A,
        action="git rm -r --cached .sfdx node_modules  (add to .gitignore)",
        message="Local CLI/npm state (.sfdx/, node_modules/) is tracked in git — untrack it.",
        dedup_key="project.tracked-ignorable",
        kind=HYGIENE_KIND,
    )


_EMPTY_SCAFFOLD_FALLBACK_ACTION = "generate a component (Apex, Agent, Analytics or UI Bundle)"

# Creation-template id (sfdx-project.json top-level `template`) -> tailored
# action. Lookup only — never format the raw template value into a string (see
# build_empty_scaffold); an id absent from this table (including None, "empty", and anything
# unrecognized) falls back to _EMPTY_SCAFFOLD_FALLBACK_ACTION.
_EMPTY_SCAFFOLD_ACTION_BY_TEMPLATE = {
    "standard": "generate a component (Apex class, LWC, or Flow)",
    "analytics": "generate a CRM Analytics app or dashboard",
    "agent": "add a topic, action, or Apex class to your agent",
    "reactinternalapp": "generate a React or Angular UI bundle",
    "reactexternalapp": "generate a React or Angular UI bundle",
    "angularinternalapp": "generate a React or Angular UI bundle",
    "angularexternalapp": "generate a React or Angular UI bundle",
    # "empty" is intentionally absent — a blank project gets the broad fallback menu.
}


@rule
def build_empty_scaffold(i: NudgeInputs) -> Optional[Candidate]:
    if "Project" not in i.reached or i.has_source:
        return None
    action = _EMPTY_SCAFFOLD_ACTION_BY_TEMPLATE.get(i.project_template, _EMPTY_SCAFFOLD_FALLBACK_ACTION)
    return Candidate(
        id="build.empty-scaffold", stage="Build", severity=SEV_ROUTINE, confidence=CONFIDENCE_A,
        action=action,
        message="Project has no local source yet.",
        dedup_key="build.empty-scaffold",
    )


# Creation-template id -> tailored FIRST-BUILD action for a project that ships
# sample/boilerplate source and was JUST scaffolded (see build_just_scaffolded).
# Distinct from _EMPTY_SCAFFOLD_ACTION_BY_TEMPLATE because the right first move
# differs: a react/angular starter isn't runnable until its npm deps are installed,
# and an agent scaffold ships a sample agent to extend — so "deploy it" is premature.
# Lookup only; an id absent here (including None) falls back to the broad build menu.
_JUST_SCAFFOLDED_ACTION_BY_TEMPLATE = {
    "agent": "add a topic, action, or Apex class to your agent",
    "reactinternalapp": "install npm deps, then build out your app",
    "reactexternalapp": "install npm deps, then build out your app",
    "angularinternalapp": "install npm deps, then build out your app",
    "angularexternalapp": "install npm deps, then build out your app",
}


@rule
def build_just_scaffolded(i: NudgeInputs) -> Optional[Candidate]:
    # The freshly-generated-SOURCE complement of build_empty_scaffold. Templates that
    # ship sample source (agent, the UI-bundle set) read has_source=True the instant
    # they land, so build_empty_scaffold bows out and — absent this rule — the ladder
    # winner right after a scaffold is deploy_never_deployed. But "deploy the untouched
    # sample" is the wrong first move (deps aren't installed / it's boilerplate to build
    # on), so at the scaffold splash (the ONLY surface that sets just_scaffolded) offer a
    # Build-stage "start building" nudge instead; deploy_never_deployed gates off the same
    # signal. Transient by design: just_scaffolded defaults False, so this never fires on a
    # later "what's next" and a genuine "you have source, never deployed" nudge returns the
    # moment the splash is past. Lands at rung 4 (Build is the frontier once source exists),
    # which is exactly right — a real Connect/Test gap still outranks "start building".
    if not i.just_scaffolded or not i.has_source:
        return None
    action = _JUST_SCAFFOLDED_ACTION_BY_TEMPLATE.get(i.project_template, _EMPTY_SCAFFOLD_FALLBACK_ACTION)
    return Candidate(
        id="build.just-scaffolded", stage="Build", severity=SEV_ROUTINE, confidence=CONFIDENCE_A,
        action=action,
        message="Project just scaffolded — start building.",
        dedup_key="build.just-scaffolded",
    )


# --------------------------------------------------------------------------- #
# Test / quality
# --------------------------------------------------------------------------- #
@rule
def test_apex_no_tests(i: NudgeInputs) -> Optional[Candidate]:
    # On the immediate post-scaffold splash the only Apex on disk is the template's
    # sample code, not the user's — nudging them to test boilerplate they haven't
    # touched is premature (same reasoning as deploy_never_deployed's just_scaffolded
    # guard). Stay quiet; the scaffold's own Build hint carries the splash.
    if not i.has_apex_classes or i.has_tests or i.just_scaffolded:
        return None
    return Candidate(
        id="test.apex-no-tests", stage="Test", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="platform-apex-test-generate",
        message="Apex classes on disk have no tests — add coverage before you deploy.",
        dedup_key="test.apex-no-tests",
    )


@rule
def test_deploy_no_test_ever(i: NudgeInputs) -> Optional[Candidate]:
    if not i.has_prior_deploy_success or i.any_test_event_ever:
        return None
    return Candidate(
        id="test.deploy-no-test-ever", stage="Test", severity=SEV_RISK, confidence=CONFIDENCE_B,
        action="platform-apex-test-run",
        message="Deployed with no test run on record — run tests for real coverage evidence.",
        dedup_key="test.deploy-no-test-ever",
        evidence_ts=i.last_deploy_passed_ts or 0.0,
    )


@rule
def test_failed_needs_fix(i: NudgeInputs) -> Optional[Candidate]:
    # Non-decay: a Test/failed record never un-lights a passed Test milestone. This
    # rule only raises a distinct, actionable warning candidate alongside it (design
    # doc cross-cutting decision #1) — it never mutates or suppresses the milestone.
    if not i.test_failed_unresolved:
        return None
    return Candidate(
        id="test.failed-needs-fix", stage="Test", severity=SEV_BLOCKING, confidence=CONFIDENCE_B,
        action="dx-devops-test-failures-analyze  (or platform-apex-logs-debug for a runtime exception)",
        message="A test failed with no later pass — fix it before moving on.",
        dedup_key="test.failed-needs-fix",
        evidence_ts=i.last_test_failed_ts or 0.0,
    )


@rule
def test_static_analysis_never_run(i: NudgeInputs) -> Optional[Candidate]:
    # has_code_analyzer_run_ever is itself a durable historical fact (a Tier-C
    # "ran once" activity record's mere ABSENCE, read back at Tier-B confidence) —
    # never a standalone Tier-C candidate, per the confidence-floor invariant.
    # Suppressed on the post-scaffold splash: the Apex on disk is template sample
    # code, so "run static analysis" is premature there (see test_apex_no_tests).
    if not i.has_apex_classes or i.has_code_analyzer_run_ever or i.just_scaffolded:
        return None
    return Candidate(
        id="test.static-analysis-never-run", stage="Test", severity=SEV_ROUTINE, confidence=CONFIDENCE_B,
        action="dx-code-analyzer-run  (or dx-apexguru-scan)",
        message="Static analysis has never run on this project's Apex — catch issues before they ship.",
        dedup_key="test.static-analysis-never-run",
        kind=HYGIENE_KIND,
    )


# --------------------------------------------------------------------------- #
# Deploy / release
# --------------------------------------------------------------------------- #
@rule
def deploy_never_deployed(i: NudgeInputs) -> Optional[Candidate]:
    # just_scaffolded suppresses this: right after a scaffold the local "source" is
    # untouched template boilerplate, not something authored and ready to ship, so
    # "deploy it" is premature — build_just_scaffolded offers the right first move
    # instead. The nudge returns on any later surface (just_scaffolded defaults False).
    if not i.has_source or i.has_prior_deploy_success or i.just_scaffolded:
        return None
    return Candidate(
        id="deploy.never-deployed", stage="Deploy", severity=SEV_ROUTINE, confidence=CONFIDENCE_A,
        action="platform-metadata-deploy  (validate-first if this org is production)",
        message="Local source never deployed to this org.",
        dedup_key="deploy.never-deployed",
    )


@rule
def deploy_uncommitted_in_pkg(i: NudgeInputs) -> Optional[Candidate]:
    if i.dirty_paths_in_pkg_roots <= 0 or not i.has_prior_deploy_success:
        return None
    n = i.dirty_paths_in_pkg_roots
    return Candidate(
        id="deploy.uncommitted-in-pkg", stage="Deploy", severity=SEV_ROUTINE, confidence=CONFIDENCE_A,
        action="platform-metadata-deploy",
        message=f"Package-directory source changed since the last deploy ({n} file(s)).",
        dedup_key="deploy.uncommitted-in-pkg", evidence_fp=str(n),
    )


@rule
def deploy_destructive_manifest(i: NudgeInputs) -> Optional[Candidate]:
    if not i.destructive_manifest_present:
        return None
    return Candidate(
        id="deploy.destructive-manifest", stage="Deploy", severity=SEV_RISK, confidence=CONFIDENCE_A,
        action="platform-destructive-deploy",
        message="This project has an undeployed destructiveChanges manifest.",
        dedup_key="deploy.destructive-manifest",
    )


# --------------------------------------------------------------------------- #
# Observe / operate
# --------------------------------------------------------------------------- #
@rule
def observe_deploy_unverified(i: NudgeInputs) -> Optional[Candidate]:
    if not i.deploy_unverified:
        return None
    return Candidate(
        id="observe.deploy-unverified", stage="Observe", severity=SEV_ROUTINE, confidence=CONFIDENCE_B,
        action="sf org open  (or pull a log if the change is Apex-behavioral)",
        message="Deploy landed but nothing shows you checked it in the org.",
        dedup_key="observe.deploy-unverified",
        evidence_ts=i.last_deploy_passed_ts or 0.0,
    )


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #
_CONF_RANK = {CONFIDENCE_A: 0, CONFIDENCE_B: 1}
_RUNG_INLINE_MAX = 5  # rungs 1..5 render inline; higher only in the `journey hints` list


def _latest_reached(reached: frozenset) -> Optional[str]:
    """The frontier: the last stage in canonical order that has evidence."""
    present = [name for name in STAGE_ORDER if name in reached]
    return present[-1] if present else None


def _rung(c: Candidate, reached: frozenset, frontier: Optional[str]) -> int:
    """The strict priority ladder. Lower is stronger; 99 means 'never inline'."""
    if c.severity >= SEV_BLOCKING and c.confidence in (CONFIDENCE_A, CONFIDENCE_B):
        return 1
    unreached = c.stage not in reached
    if unreached and c.confidence == CONFIDENCE_A:
        return 2
    if unreached and c.confidence == CONFIDENCE_B:
        return 3
    if c.stage == frontier:
        return 4
    # Connect-stage facts are live operational preconditions, not one-time
    # progress gaps: unlike e.g. project_no_git, they don't stay resolved just
    # because the frontier moved on, so frontier movement must not silence
    # them once they're RISK+ and backed by a hook/org fact.
    if c.stage == "Connect" and c.severity >= SEV_RISK and c.confidence in (CONFIDENCE_A, CONFIDENCE_B):
        return 5
    return 99


def _sort_key(item: tuple[int, Candidate]) -> tuple:
    rung, c = item
    return (
        rung,
        -c.severity,
        _CONF_RANK.get(c.confidence, 9),
        -c.evidence_ts,
        STAGE_ORDER.index(c.stage) if c.stage in STAGE_ORDER else len(STAGE_ORDER),
        c.id,
    )


def _ranked(inputs: NudgeInputs) -> list[tuple[int, Candidate]]:
    """Every Gate-0-surviving candidate, paired with its rung, ladder-sorted."""
    reached = inputs.reached if isinstance(inputs.reached, frozenset) else frozenset(inputs.reached or ())
    frontier = _latest_reached(reached)
    ranked: list[tuple[int, Candidate]] = []
    for fn in _RULES:
        # Defensive: the registry docstring promises rules never raise, but one bad
        # rule must not take down the whole render (this feeds the SessionStart hot
        # path from Phase 2 on) — skip it and keep every other candidate.
        try:
            c = fn(inputs)
        except Exception:
            continue
        if c is None or not c.action:  # Gate 0: must be actionable
            continue
        ranked.append((_rung(c, reached, frontier), c))
    ranked.sort(key=_sort_key)
    return ranked


def select(inputs: NudgeInputs) -> Optional[Candidate]:
    """The single best nudge to render inline, or None if nothing qualifies."""
    for rung, c in _ranked(inputs):
        if rung <= _RUNG_INLINE_MAX:
            return c
    return None


def select_for_scaffold(inputs: NudgeInputs) -> Optional[Candidate]:
    """Inline selection for the immediate post-scaffold splash (cmd_scaffold_paint).

    Same holistic ladder as `select` — a genuine earlier-stage gap (no org
    connected) or a live blocker still wins, so the splash stays honest about where
    the user actually is in their journey. The one difference is the *fallback*: when
    the ladder has nothing to say, offer the fresh-scaffold Build hint rather than an
    empty slot. That hint is otherwise rung-99 for a source-shipping template
    (`reactexternalapp`, `agent`, …) — the boilerplate it lands lights Build (and
    often Test), so Build is a reached, non-frontier stage and the normal ladder
    drops "start building" as already-done. It isn't done: that source is the
    template's, not the user's. Falling back to it here keeps the ladder unchanged
    for every other surface while guaranteeing the splash always points at a next
    step. Deliberately plugin-agnostic — plugin recommendations are the dynamic
    plugin-loading layer's job, not the journey hint's.
    """
    winner = select(inputs)
    if winner is not None:
        return winner
    return build_just_scaffolded(inputs) or build_empty_scaffold(inputs)


def is_uncapped(candidate: Optional[Candidate]) -> bool:
    """Whether `candidate` is a rung-1 blocking candidate — the one class of nudge
    the anti-nag session cap (sf_context, journey-nudges Phase 4) must never hold
    back. Mirrors rung 1's own test in `_rung` exactly (severity >= SEV_BLOCKING at
    Tier-A/B confidence) so the two can never drift: a live blocker always earns
    its render, uncapped, per the design doc's anti-nag section ("Rung-1 blocking
    nudges are uncapped — a live fire always earns its render"). A pure function of
    the candidate alone, so `sf_context` never has to duplicate rung logic."""
    return (
        candidate is not None
        and candidate.severity >= SEV_BLOCKING
        and candidate.confidence in (CONFIDENCE_A, CONFIDENCE_B)
    )


def all_hints(inputs: NudgeInputs) -> list[Candidate]:
    """Every applicable, actionable nudge, ranked — for the `journey hints` command."""
    return [c for _, c in _ranked(inputs)]


# --------------------------------------------------------------------------- #
# Presentation — the graded band label a surface prepends to a nudge
# --------------------------------------------------------------------------- #
# The visible label (emoji + word) a renderer leads a nudge with. Keyed off the
# candidate's severity, with `hygiene` (a SEV_ROUTINE sub-kind, tagged on the rule
# via Candidate.kind) split out of the momentum band. PRESENTATION-ONLY: chosen at
# render time from the already-selected candidate, so it never enters dedup_key /
# evidence_fp or the selection ladder (`_rung`/`_ranked`) — changing a label can't
# change which nudge wins or trip the anti-nag cap. Kept here (not in sf_context) as
# the single source of truth: both renderers call `band_label`, neither hardcodes
# the mapping. Mirrors the pure, sf_context-agnostic `is_uncapped` pattern above.
HYGIENE_KIND = "hygiene"

BAND_FIX = ("❌", "Fix")                    # ❌  SEV_BLOCKING — a command you need fails now
BAND_HEADS_UP = ("⚠️", "Heads up")    # ⚠️  SEV_RISK — exposed; nothing broken yet
BAND_TRY_NEXT = ("\U0001f680", "Try next")      # 🚀  SEV_ROUTINE momentum — the natural next move
BAND_TIDY = ("✨", "Tidy")                  # ✨  SEV_ROUTINE hygiene / SEV_OPTIONAL — polish


def band_label(candidate: Candidate) -> tuple[str, str]:
    """The (emoji, label) presentation band for `candidate`. Pure, and
    presentation-only (see the section note). BLOCKING → Fix, RISK → Heads up,
    ROUTINE → Try next — unless the rule is tagged ``kind="hygiene"``, which drops
    it to Tidy alongside SEV_OPTIONAL. The Tidy band is also the catch-all: any
    severity below BLOCKING that isn't RISK or non-hygiene ROUTINE (SEV_OPTIONAL, a
    hygiene ROUTINE, or an unrecognized/negative value) resolves to the softest
    band, so a future or malformed severity can never crash a render. A value at or
    above SEV_BLOCKING is treated as Fix (an escalated future band stays loudest)."""
    severity = candidate.severity
    if severity >= SEV_BLOCKING:
        return BAND_FIX
    if severity == SEV_RISK:
        return BAND_HEADS_UP
    if severity == SEV_ROUTINE and candidate.kind != HYGIENE_KIND:
        return BAND_TRY_NEXT
    return BAND_TIDY


def band_labels() -> tuple[tuple[str, str], ...]:
    """The closed set of every band's (emoji, label), for callers that need it
    without a candidate — e.g. a renderer deriving its width-exemption prefixes, or
    a drift test asserting a sf_context-side mirror stays in sync."""
    return (BAND_FIX, BAND_HEADS_UP, BAND_TRY_NEXT, BAND_TIDY)


def band_word(candidate: Candidate) -> str:
    """The plain-text band word only (no emoji) — the label half of `band_label`,
    for a surface that strips emoji (screen readers / low-capability terminals) but
    must still ANNOUNCE the band so the same urgency/kind carries. Derived from
    `band_label`, never a second word list, so the two can't drift: same catch-all
    behavior (SEV_OPTIONAL / hygiene / unknown → "Tidy")."""
    return band_label(candidate)[1]


def band_words() -> tuple[str, ...]:
    """The closed set of every band's plain-text word, in `band_labels` order — the
    words-only view of the taxonomy, for a drift/exhaustiveness test."""
    return tuple(label for _emoji, label in band_labels())
