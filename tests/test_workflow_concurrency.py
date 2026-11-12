#!/usr/bin/env python3
"""Verify PR stale-SHA cancellation and non-PR run isolation across workflows and templates."""
from __future__ import annotations

import pathlib
import unittest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PR_GUARD = "github.event_name == 'pull_request'"
PR_KEY_FRAGMENT = "format('{0}-pr-{1}', github.workflow, github.event.pull_request.number)"
RUN_KEY_FRAGMENT = "format('{0}-run-{1}', github.workflow, github.run_id)"
EXPECTED_CANCEL = "${{ github.event_name == 'pull_request' }}"


def validate_concurrency_block(concurrency: object, context: str) -> list[str]:
    if not isinstance(concurrency, dict):
        return [f"{context}: missing concurrency mapping"]
    errors: list[str] = []
    if set(concurrency.keys()) != {"group", "cancel-in-progress"}:
        errors.append(f"{context}: concurrency must contain exactly group and cancel-in-progress")
    group = concurrency.get("group")
    cancel = concurrency.get("cancel-in-progress")
    if not isinstance(group, str) or PR_GUARD not in group or PR_KEY_FRAGMENT not in group or RUN_KEY_FRAGMENT not in group:
        errors.append(
            f"{context}: group must isolate pull_request by PR number and non-PR runs by run_id (got {group!r})"
        )
    if isinstance(group, str) and "github.ref" in group:
        errors.append(f"{context}: group must not key non-PR runs on github.ref")
    if cancel != EXPECTED_CANCEL:
        errors.append(
            f"{context}: cancel-in-progress must equal {EXPECTED_CANCEL!r} so non-PR runs never cancel (got {cancel!r})"
        )
    return errors


def validate_workflow_yaml(text: str, source: str) -> list[str]:
    doc = yaml.safe_load(text) or {}
    top = doc.get("concurrency")
    if top is not None:
        return validate_concurrency_block(top, source)
    jobs = doc.get("jobs") or {}
    if not jobs:
        return [f"{source}: workflow defines no jobs"]
    errors: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict) or "uses" in job:
            continue
        errors.extend(validate_concurrency_block(job.get("concurrency"), f"{source}:jobs.{job_id}"))
    if not errors and all(isinstance(j, dict) and "uses" in j for j in jobs.values()):
        errors.append(f"{source}: caller-only workflow must declare top-level concurrency")
    return errors


class WorkflowConcurrencyTests(unittest.TestCase):
    def test_repository_workflows_and_templates_enforce_pr_concurrency(self) -> None:
        targets = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
            (REPO_ROOT / "workflow-templates").glob("*.yml")
        )
        self.assertGreaterEqual(len(targets), 10)
        problems: list[str] = []
        for path in targets:
            rel = path.relative_to(REPO_ROOT).as_posix()
            problems.extend(validate_workflow_yaml(path.read_text(encoding="utf-8"), rel))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_reusable_workflow_groups_are_disjoint_within_same_caller_run(self) -> None:
        groups: list[str] = []
        for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            if path.name == "ci.yml":
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if "concurrency" in doc:
                groups.append(doc["concurrency"]["group"])
            else:
                for job in (doc.get("jobs") or {}).values():
                    groups.append(job["concurrency"]["group"])
        prefixes = [g.split("$", 1)[0] for g in groups]
        self.assertEqual(len(prefixes), len(set(prefixes)), f"duplicate reusable group prefixes: {prefixes}")
        self.assertTrue(all(p.endswith("-") and len(p) > 1 for p in prefixes), f"unprefixed reusable group: {prefixes}")

    def test_negative_missing_or_unsafe_concurrency_rejected(self) -> None:
        missing = "on: [pull_request, push]\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"
        self.assertTrue(validate_workflow_yaml(missing, "missing.yml"))

        unconditional_cancel = (
            "on: [pull_request, push]\n"
            "concurrency:\n"
            "  group: ${{ github.event_name == 'pull_request' && format('{0}-pr-{1}', github.workflow, github.event.pull_request.number) || format('{0}-run-{1}', github.workflow, github.run_id) }}\n"
            "  cancel-in-progress: true\n"
            "jobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"
        )
        self.assertTrue(validate_workflow_yaml(unconditional_cancel, "unconditional.yml"))

        ref_collision = (
            "on: [pull_request, push]\n"
            "concurrency:\n"
            "  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}\n"
            "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
            "jobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"
        )
        self.assertTrue(validate_workflow_yaml(ref_collision, "ref.yml"))


if __name__ == "__main__":
    unittest.main()
