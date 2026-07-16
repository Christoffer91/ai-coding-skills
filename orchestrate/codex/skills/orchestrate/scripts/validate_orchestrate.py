#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


EXPECTED = {
    "orchestrate_planner": ("gpt-5.6-sol", "ultra", "read-only", 2),
    "orchestrate_plan_critic": ("gpt-5.6-sol", "high", "read-only", 1),
    "orchestrate_explorer": ("gpt-5.6-sol", "high", "read-only", 1),
    "orchestrate_explorer_deep": ("gpt-5.6-sol", "xhigh", "read-only", 1),
    "orchestrate_executor": ("gpt-5.6-terra", "medium", "workspace-write", 1),
    "orchestrate_reviewer": ("gpt-5.6-sol", "ultra", "read-only", 2),
}
EXPECTED_SCENARIOS = {
    "dry-run",
    "direct-qa",
    "fast-mechanical-change",
    "standard-spec-critique",
    "deep-security-external-critique",
    "explicit-orchestrate-external-review",
    "explicit-orchestrate-preflight-failure",
    "explicit-orchestrate-data-policy-consumption",
    "explicit-orchestrate-timeout-consumption",
    "explicit-orchestrate-internal-only",
    "failure-escalation",
    "approved-plan-resume",
    "local-explicit-no-git-write",
    "pr-ready-happy-path",
    "pr-ready-merge-authorized",
    "merge-is-deploy-gate",
    "authorization-invalidated-on-scope-change",
}


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    agents_dir = skill_dir.parents[1] / "agents"
    errors: list[str] = []

    for name, expected in EXPECTED.items():
        path = agents_dir / f"{name}.toml"
        if not path.exists():
            errors.append(f"missing agent: {path}")
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"invalid agent {name}: {exc}")
            continue
        actual = (
            data.get("model"),
            data.get("model_reasoning_effort"),
            data.get("sandbox_mode"),
            data.get("agents", {}).get("max_depth"),
        )
        if actual != expected:
            errors.append(f"{name}: expected {expected}, found {actual}")

    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for name in EXPECTED:
        if name not in skill_text:
            errors.append(f"SKILL.md does not reference {name}")
    for required in (
        "DRY_RUN",
        "without spawning agents",
        "only source writer",
        "Every `FULL_SPEC`",
        "FAST -> STANDARD -> DEEP",
        "orchestrate_plan_critic",
        "standing authorization",
        "--approved-outbound",
        "same turn",
        "Implicit routing",
        "internal-only",
        "external_review_allowance: unused",
        "`unused|consumed`",
        "atomically compare and set",
        "JSON `command` array",
        "underlying Claude command",
        "Every dispatched attempt remains consumed",
        "Claude failure",
        "timeout",
        "malformed output",
        "missing model metadata",
        "tool/data-policy rejection",
        "eligible Fable-to-Opus fallback",
        "new explicit `$orchestrate` invocation",
        "preflight failure",
        "Goal-scoped action authorization",
        "Never ask again",
        "user an obligatory reviewer",
        "merge triggers publishing or production deployment",
        "matching goal-scoped grant",
        "incidental mentions, questions, examples, and negated instructions do not",
        "grants only that named action",
    ):
        if required not in skill_text:
            errors.append(f"SKILL.md missing contract text: {required}")

    pipeline_dir = skill_dir.parent / "pipeline"
    pipeline_text = (pipeline_dir / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        "EXECUTION_PROFILE=AUTO|DIRECT|FAST|STANDARD|DEEP",
        "MICRO_SPEC",
        "FULL_SPEC",
        "CALLER=orchestrate",
        "CONTRACT_ONLY",
        "no executor may run",
    ):
        if required not in pipeline_text:
            errors.append(f"pipeline missing contract text: {required}")
    spec_reference = pipeline_dir / "references/spec-driven-plan.md"
    if not spec_reference.is_file():
        errors.append(f"missing spec-driven plan reference: {spec_reference}")

    claude_reference = skill_dir / "references/claude-plan-critique.md"
    if not claude_reference.is_file():
        errors.append(f"missing Claude critique reference: {claude_reference}")
    else:
        claude_text = claude_reference.read_text(encoding="utf-8")
        for required in (
            "explicit approval",
            "--model fable",
            "--fallback-model opus",
            "--safe-mode",
            '--tools ""',
            "stdin",
            "standing authorization",
            "--approved-outbound",
            "same turn",
            "redundant second approval",
            "JSON `command` array",
            "shell-escaped informational argv",
            "not the `run-review` wrapper",
            "atomically change the allowance",
            "`unused` to `consumed`",
            "Any runner dispatch consumes",
            "failed preflight sends no packet",
            "separate explicit outbound approval",
        ):
            if required not in claude_text:
                errors.append(f"Claude critique reference missing: {required}")
        if "--dangerously-skip-permissions" in claude_text:
            errors.append("Claude critique reference must not mention a dangerous permission bypass")
        if "intended to resolve to Opus 4.8" in claude_text:
            errors.append("Claude critique reference must not infer Opus 4.8 from an alias")
    claude_final_review = skill_dir / "references/claude-final-review.md"
    if not claude_final_review.is_file():
        errors.append(f"missing Claude final review reference: {claude_final_review}")
    else:
        final_review_text = claude_final_review.read_text(encoding="utf-8")
        for required in (
            "standing authorization",
            "--approved-outbound",
            "same turn",
            "redundant second approval",
            "separate explicit approval",
            "additional paid call",
            "JSON `command` array",
            "shell-escaped informational argv",
            "not the `run-review` wrapper",
            "atomically change the allowance",
            "Any runner dispatch consumes",
            "failed preflight sends no packet",
            "plan critique already consumed",
        ):
            if required not in final_review_text:
                errors.append(f"Claude final review reference missing: {required}")
    claude_preflight = skill_dir / "references/claude-cli-preflight.md"
    if not claude_preflight.is_file():
        errors.append(f"missing Claude CLI preflight reference: {claude_preflight}")
    else:
        preflight_text = claude_preflight.read_text(encoding="utf-8")
        for required in (
            "same absolute path",
            "auth status --json",
            "omit `--max-budget-usd`",
            "monthly Agent SDK allowance",
            "exactly once",
            "modelUsage",
            "estimated model cost",
            "standing outbound authorization",
            "--approved-outbound",
            "same turn",
            "redundant second approval",
            "internal-only",
            "default `$2` metered cap",
            "zero retries after data-policy rejection",
            "`command` to be an array of strings",
            "without adding, removing, or reordering argv",
            "not the shared `run-review` wrapper",
            "printing it is not an approval gate",
            "atomically compare and set",
            "EXTERNAL_REVIEW_BLOCKED:preflight",
            "leaves the allowance `unused`",
            "keep `external_review_allowance: consumed`",
            "timeout",
        ):
            if required not in preflight_text:
                errors.append(f"Claude CLI preflight reference missing: {required}")
        if "resolved `run-review` command" in preflight_text:
            errors.append("Claude CLI preflight must not label its command array as a resolved run-review command")

    writable = [name for name, (_, _, sandbox, _) in EXPECTED.items() if sandbox == "workspace-write"]
    if writable != ["orchestrate_executor"]:
        errors.append(f"expected one writer, found: {', '.join(writable)}")

    scenarios_path = skill_dir / "references/scenario-evals.json"
    try:
        scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid scenario evals: {exc}")
        scenarios = []
    by_id = {
        item.get("id"): item
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(by_id) != EXPECTED_SCENARIOS:
        errors.append(f"scenario ids differ: expected {sorted(EXPECTED_SCENARIOS)}, found {sorted(by_id)}")
    else:
        dry_run = by_id["dry-run"]
        if dry_run.get("writes") is not False or dry_run.get("spawn_roles") != []:
            errors.append("dry-run scenario must not write or spawn agents")
        if (
            dry_run.get("explicit_skill_invocation") is not True
            or dry_run.get("standing_authorization_overridden") is not True
            or dry_run.get("local_preflight_executed") is not False
            or dry_run.get("external_review_executed") is not False
        ):
            errors.append("DRY_RUN must override explicit-invocation external authorization")
        direct = by_id["direct-qa"]
        if direct.get("spawn_roles") != [] or direct.get("spec_mode") != "NONE":
            errors.append("direct-qa scenario must not spawn agents or create an implementation spec")
        fast = by_id["fast-mechanical-change"]
        if fast.get("spawn_roles") != ["orchestrate_executor"] or fast.get("sol_ultra_calls") != 0:
            errors.append("FAST scenario must use only the Terra executor and zero Sol Ultra calls")
        standard = by_id["standard-spec-critique"]
        if standard.get("spawn_roles") != [
            "orchestrate_planner",
            "orchestrate_plan_critic",
            "orchestrate_executor",
            "orchestrate_reviewer",
        ]:
            errors.append("STANDARD scenario has incorrect role order")
        if standard.get("planner_effort") != "ultra" or standard.get("critique_required") is not True:
            errors.append("STANDARD scenario must use an Ultra full spec and fresh critique")
        critique_off = standard.get("critique_off_execute", {})
        if critique_off.get("executor_spawned") is not False or critique_off.get("terminal") != "AWAIT_APPROVAL":
            errors.append("PLAN_CRITIQUE=OFF must block FULL_SPEC execution before the executor")
        failure = by_id["failure-escalation"]
        if failure.get("diagnostic_skill") != "systematic-debugging" or failure.get("silent_model_upgrade") is not False:
            errors.append("failure-escalation scenario must diagnose without silently upgrading the writer")
        if failure.get("allowed_direction") != "FAST->STANDARD->DEEP":
            errors.append("profile escalation must be one-way")
        security = by_id["deep-security-external-critique"]
        if (
            security.get("explorer") != "orchestrate_explorer_deep"
            or security.get("risk_gate") is not True
            or security.get("external_approval_required") is not True
            or security.get("explicit_skill_invocation") is not False
            or security.get("standing_external_review_authorization") is not False
        ):
            errors.append("implicit DEEP security routing must retain deep evidence, risk, and external approval gates")
        if (
            security.get("claude_absolute_binary_required") is not True
            or security.get("claude_auth_preflight_required") is not True
            or security.get("subscription_default_budget_flag") != "omitted"
            or security.get("metered_default_budget_usd") != 2
            or security.get("direct_opus_fallback_limit") != 1
            or security.get("direct_opus_fallback_trigger") != "strict-fable-unavailable-only"
            or security.get("shared_claude_runner_required") is not True
            or security.get("result_model_metadata_required") is not True
            or security.get("data_policy_rejection_state") != "EXTERNAL_REVIEW_BLOCKED:data-policy"
            or security.get("data_policy_retry_limit") != 0
            or security.get("optional_external_fallback") != "internal-reviewer"
            or security.get("required_external_gate") != "single-human-decision"
            or security.get("baton_polling") is not False
        ):
            errors.append("external Claude scenario must enforce binary, auth, budget, fallback, metadata, and data-policy bounds")
        explicit_external = by_id["explicit-orchestrate-external-review"]
        if (
            explicit_external.get("explicit_skill_invocation") is not True
            or explicit_external.get("external_lane_selected") is not True
            or explicit_external.get("standing_external_review_authorization") is not True
            or explicit_external.get("secret_free_packet_required") is not True
            or explicit_external.get("local_preflight_required") is not True
            or explicit_external.get("extra_comparative_paid_calls_authorized") is not False
            or explicit_external.get("subscription_metered_policy_unchanged") is not True
            or explicit_external.get("data_policy_retry_limit") != 0
        ):
            errors.append("explicit $orchestrate must preserve the bounded external-review policy")
        expected_preflight_command = {
            "source": "preflight-json.command",
            "type": "array-of-strings",
            "rendering": "shell-escaped-without-argv-mutation",
            "represents": "underlying-claude-argv",
            "is_run_review_wrapper": False,
            "informational_only": True,
        }
        if explicit_external.get("preflight_output_command") != expected_preflight_command:
            errors.append("explicit review must render the exact preflight command array as informational underlying Claude argv")
        expected_allowance = {
            "scope": "explicit-invocation",
            "states": ["unused", "consumed"],
            "initial": "unused",
            "required_before_standing_dispatch": "unused",
            "transition": "atomic-unused-to-consumed-immediately-before-run-review-dispatch",
            "after_any_dispatch_attempt": "consumed",
        }
        if explicit_external.get("allowance") != expected_allowance:
            errors.append("explicit review must use an invocation-scoped atomic unused-to-consumed allowance")
        expected_dispatch = {
            "entrypoint": "shared-runner:run-review",
            "known_inputs": ["packet", "output"],
            "approved_outbound": True,
            "same_turn_as_progress": True,
        }
        if explicit_external.get("runner_dispatch") != expected_dispatch:
            errors.append("explicit review must dispatch the shared runner with known I/O and approved outbound in the same turn")
        expected_sequence = [
            {
                "stage": "plan-critique",
                "reviewer": "internal-orchestrate-plan-critic",
                "allowance_after_stage": "unused",
            },
            {
                "stage": "final-review",
                "authorization": "standing-unused-allowance",
                "allowance_after_dispatch": "consumed",
            },
        ]
        if explicit_external.get("review_sequence") != expected_sequence:
            errors.append("the default route must preserve the one external allowance for final review")
        expected_exclusions = {
            "extra-or-comparative-paid-calls",
            "secrets-customer-data-or-raw-transcripts",
            "policy-bypass",
            "push-pr-creation-merge-or-deploy",
            "install-migration-or-destructive-action",
            "tenant-or-live-calls",
            "all-other-hard-gates",
        }
        if set(explicit_external.get("standing_authorization_excludes", [])) != expected_exclusions:
            errors.append("explicit invocation standing authorization must preserve every unrelated hard gate")
        preflight_failure = by_id["explicit-orchestrate-preflight-failure"]
        if (
            preflight_failure.get("allowance_before") != "unused"
            or preflight_failure.get("preflight_result") != "failure-before-runner-dispatch"
            or preflight_failure.get("runner_dispatch_attempted") is not False
            or preflight_failure.get("review_packet_sent") is not False
            or preflight_failure.get("allowance_after") != "unused"
            or preflight_failure.get("disposition") != "EXTERNAL_REVIEW_BLOCKED:preflight"
            or preflight_failure.get("optional_external_fallback") != "internal-reviewer"
        ):
            errors.append("preflight failure must send no packet, preserve unused allowance, and record the blocked disposition")
        data_policy = by_id["explicit-orchestrate-data-policy-consumption"]
        if (
            data_policy.get("allowance_before") != "unused"
            or data_policy.get("allowance_transition") != "atomic-unused-to-consumed-immediately-before-run-review-dispatch"
            or data_policy.get("runner_dispatch_attempted") is not True
            or data_policy.get("tool_rejected_before_packet_sent") is not True
            or data_policy.get("allowance_after") != "consumed"
            or data_policy.get("disposition") != "EXTERNAL_REVIEW_BLOCKED:data-policy"
            or data_policy.get("data_policy_retry_limit") != 0
            or data_policy.get("later_standing_dispatch_allowed") is not False
        ):
            errors.append("a dispatched data-policy rejection must consume the allowance with zero retries")
        timeout = by_id["explicit-orchestrate-timeout-consumption"]
        if (
            timeout.get("allowance_before") != "unused"
            or timeout.get("allowance_transition") != "atomic-unused-to-consumed-immediately-before-run-review-dispatch"
            or timeout.get("runner_dispatch_attempted") is not True
            or timeout.get("runner_result") != "timeout"
            or timeout.get("allowance_after") != "consumed"
            or timeout.get("external_retry_allowed") is not False
            or timeout.get("later_standing_dispatch_allowed") is not False
        ):
            errors.append("a dispatched timeout must consume the allowance and forbid another standing-authorized pass")
        internal_only = by_id["explicit-orchestrate-internal-only"]
        if (
            internal_only.get("explicit_skill_invocation") is not True
            or internal_only.get("internal_only_instruction") is not True
            or internal_only.get("standing_authorization_overridden") is not True
            or internal_only.get("local_preflight_executed") is not False
            or internal_only.get("external_review_executed") is not False
        ):
            errors.append("explicit internal-only instructions must override standing external authorization")
        resume = by_id["approved-plan-resume"]
        if (
            resume.get("planner_spawned") is not False
            or resume.get("critic_spawned") is not False
            or resume.get("critique_disposition") != "COMPLETE"
            or resume.get("contract_still_valid") is not True
            or resume.get("canonical_state_count") != 1
        ):
            errors.append("approved plan resume must skip replanning/recritique and retain one valid canonical state")
        local_explicit = by_id["local-explicit-no-git-write"]
        local_grants = local_explicit.get("action_grants", {})
        if (
            local_explicit.get("explicit_skill_invocation") is not True
            or local_explicit.get("negated_merge_mention") is not True
            or local_explicit.get("git_write_executed") is not False
            or local_explicit.get("merge_grant_inferred") is not False
            or local_grants.get("external_final_review") is not True
            or any(local_grants.get(action) is not False for action in ("commit", "push", "pr_write", "merge", "deploy"))
        ):
            errors.append("bare explicit LOCAL invocation grants one final review but no GitHub writes, merge, or deploy")
        pr_ready = by_id["pr-ready-happy-path"]
        pr_grants = pr_ready.get("action_grants", {})
        expected_flow = [
            "implement", "verify", "commit", "push", "pr-write", "claude-final-review",
            "validate-findings", "fix-blockers", "reverify", "push-fixes",
        ]
        if (
            any(pr_grants.get(action) is not True for action in ("commit", "push", "pr_write", "external_final_review"))
            or pr_grants.get("merge") is not False
            or pr_grants.get("deploy") is not False
            or pr_ready.get("flow") != expected_flow
            or pr_ready.get("redundant_approval_prompts") != 0
            or pr_ready.get("user_is_mandatory_reviewer") is not False
            or pr_ready.get("external_failure_fallback") != "internal-reviewer"
            or pr_ready.get("review_fix_round_limit") != 3
        ):
            errors.append("PR_READY happy path must complete PR/review/fix without redundant human gates")
        merge = by_id["pr-ready-merge-authorized"]
        if (
            merge.get("exact_active_goal_merge_grant") is not True
            or merge.get("required_checks_green") is not True
            or merge.get("final_review_validated") is not True
            or merge.get("blocking_findings") != 0
            or merge.get("mergeable") is not True
            or merge.get("merge_is_deploy") is not False
            or merge.get("merge_executed") is not True
            or merge.get("redundant_approval_prompts") != 0
        ):
            errors.append("authorized merge must execute only after every non-deploy merge gate is green")
        merge_deploy = by_id["merge-is-deploy-gate"]
        if (
            merge_deploy.get("merge_is_deploy") is not True
            or merge_deploy.get("deploy_grant") is not False
            or merge_deploy.get("merge_executed") is not False
            or merge_deploy.get("terminal") != "AWAIT_DEPLOY_AUTHORIZATION"
        ):
            errors.append("merge-triggered deploy must retain a separate deploy gate")
        invalidated = by_id["authorization-invalidated-on-scope-change"]
        if (
            invalidated.get("initial_pr_write_grant") is not True
            or invalidated.get("material_scope_change") is not True
            or invalidated.get("affected_grants_invalidated") is not True
            or invalidated.get("additional_push_executed") is not False
            or invalidated.get("merge_executed") is not False
        ):
            errors.append("material scope change must invalidate affected action grants before more writes")

    if errors:
        print("[ERROR] Orchestrate contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[OK] Adaptive pipeline profiles, goal-scoped action grants, model roles, and seventeen scenarios are aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
