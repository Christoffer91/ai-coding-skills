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
    "failure-escalation",
    "approved-plan-resume",
    "pr-ready-stop-gate",
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
        ):
            if required not in claude_text:
                errors.append(f"Claude critique reference missing: {required}")
        if "--dangerously-skip-permissions" in claude_text:
            errors.append("Claude critique reference must not mention a dangerous permission bypass")
        if "intended to resolve to Opus 4.8" in claude_text:
            errors.append("Claude critique reference must not infer Opus 4.8 from an alias")
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
        ):
            if required not in preflight_text:
                errors.append(f"Claude CLI preflight reference missing: {required}")

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
        ):
            errors.append("DEEP security scenario must use deep evidence, risk, and external approval gates")
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
        resume = by_id["approved-plan-resume"]
        if (
            resume.get("planner_spawned") is not False
            or resume.get("critic_spawned") is not False
            or resume.get("critique_disposition") != "COMPLETE"
            or resume.get("contract_still_valid") is not True
            or resume.get("canonical_state_count") != 1
        ):
            errors.append("approved plan resume must skip replanning/recritique and retain one valid canonical state")
        pr_ready = by_id["pr-ready-stop-gate"]
        if pr_ready.get("external_action_requires_explicit_authorization") is not True:
            errors.append("PR_READY scenario must gate external actions")

    if errors:
        print("[ERROR] Orchestrate contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[OK] Adaptive pipeline profiles, spec/critique gates, model roles, and eight scenarios are aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
