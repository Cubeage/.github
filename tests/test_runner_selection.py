"""Runner selection: only labels the provider serves Cubeage, and store-stills rejects the rest.

Provider contract (read 2026-11-27): SylphxAI/sylphx@5c7a1de
kernel/hands/cells/fsn1/scale-sets.toml serves Cubeage the plain classes
standard, large, xlarge, 2xlarge and control, and a merge twin only for standard
(plus the internal poller/review listeners); SylphxAI/.github
policy/merge-runner-labels.json records Cubeage as ["sylphx-linux-standard-merge"].
needs-pass refuses a merge group that selects an unserved twin.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVED_MERGE = {"sylphx-linux-standard-merge"}
EVENTS = ("pull_request", "merge_group", "push", "workflow_dispatch", "schedule")
TOKEN = re.compile(r"\s*(?:('(?:''|[^'])*')|(&&|\|\||==|!=|[!(),])|([A-Za-z_][\w.-]*))")


class Rejected(Exception):
    """The expression fails while it is evaluated, as GitHub fails the job."""


def evaluate(text: str, context: dict[str, object]) -> object:
    """GitHub's expression rules for the subset these selectors use.

    Case-insensitive string ==, && and || return an operand and short-circuit,
    fromJSON parses the first JSON token and fails on anything else.
    """
    body = text.strip()
    if not (body.startswith("${{") and body.endswith("}}")):
        return text
    tokens, pos, src = [], 0, body[3:-2].strip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot parse {src[pos:]!r}")
        tokens.append(m.groups())
        pos = m.end()
    tokens.append((None, "end", None))
    i = 0

    def peek(op: str) -> bool:
        return tokens[i][1] == op

    def take(op: str) -> None:
        nonlocal i
        if not peek(op):
            raise ValueError(f"expected {op} in {src!r}")
        i += 1

    def truthy(v: object) -> bool:
        return v not in (None, False, "", 0)

    def equal(a: object, b: object) -> bool:
        return a.lower() == b.lower() if isinstance(a, str) and isinstance(b, str) else a == b

    def call(name: str, args: list) -> object:
        values = [a() for a in args]
        if name.lower() == "format":
            return re.sub(r"\{\{|\}\}|\{(\d+)\}",
                          lambda m: m.group(0)[0] if m.group(1) is None else str(values[1 + int(m.group(1))]),
                          values[0])
        if name.lower() == "fromjson":
            try:
                return json.JSONDecoder().raw_decode(str(values[0]).lstrip())[0]
            except ValueError as err:
                raise Rejected(f"fromJSON({values[0]!r}): {err}") from err
        raise ValueError(f"unknown function {name}")

    # Each parser returns a thunk so && and || evaluate their right side lazily.
    def primary():
        nonlocal i
        literal, op, name = tokens[i]
        if literal is not None:
            i += 1
            return lambda: literal[1:-1].replace("''", "'")
        if op == "(":
            take("(")
            inner = disjunction()
            take(")")
            return inner
        if op == "!":
            take("!")
            inner = primary()
            return lambda: not truthy(inner())
        if name is None:
            raise ValueError(f"unexpected {op!r} in {src!r}")
        i += 1
        if peek("("):
            take("(")
            args = [] if peek(")") else [disjunction()]
            while peek(","):
                take(",")
                args.append(disjunction())
            take(")")
            return lambda: call(name, args)
        return lambda: context.get(name)

    def comparison():
        left = primary()
        for op in ("==", "!="):
            if peek(op):
                take(op)
                right = primary()
                return (lambda: equal(left(), right())) if op == "==" else (lambda: not equal(left(), right()))
        return left

    def conjunction():
        node = comparison()
        while peek("&&"):
            take("&&")
            node = (lambda a, b: lambda: (lambda v: b() if truthy(v) else v)(a()))(node, comparison())
        return node

    def disjunction():
        node = conjunction()
        while peek("||"):
            take("||")
            node = (lambda a, b: lambda: (lambda v: v if truthy(v) else b())(a()))(node, conjunction())
        return node

    result = disjunction()
    take("end")
    return result()


def load(rel: str) -> dict:
    # BaseLoader keeps the Actions key `on` a string (YAML 1.1 reads it as True).
    return yaml.load((ROOT / rel).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def unserved_merge_labels(text: str) -> set[str]:
    return set(re.findall(r"sylphx-linux-[\w-]+-merge", text)) - SERVED_MERGE


class TemplateSelectionTests(unittest.TestCase):
    def test_every_event_selects_a_served_pool(self) -> None:
        jobs = load("workflow-templates/ci-fast-path.yml")["jobs"]
        for event in EVENTS:
            context = {"github.event_name": event}
            with self.subTest(event=event):
                merge = event == "merge_group"
                self.assertEqual(evaluate(jobs["gate"]["runs-on"], context),
                                 "sylphx-linux-standard-merge" if merge else "sylphx-linux-standard")
                self.assertEqual(evaluate(jobs["heavy"]["runs-on"], context), "sylphx-linux-xlarge")
                self.assertEqual(evaluate(jobs["ci-ok"]["runs-on"], context), "sylphx-linux-control")

    def test_no_workflow_template_or_lint_label_names_an_unserved_twin(self) -> None:
        files = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
            (ROOT / "workflow-templates").glob("*.yml")) + [ROOT / ".github" / "actionlint.yaml"]
        found = {f.relative_to(ROOT).as_posix(): unserved_merge_labels(f.read_text(encoding="utf-8")) for f in files}
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_negative_retired_xlarge_twin_is_refused(self) -> None:
        old = "${{ github.event_name == 'merge_group' && 'sylphx-linux-xlarge-merge' || 'sylphx-linux-xlarge' }}"
        self.assertEqual(evaluate(old, {"github.event_name": "merge_group"}), "sylphx-linux-xlarge-merge")
        self.assertEqual(unserved_merge_labels(old), {"sylphx-linux-xlarge-merge"})


class StoreStillsSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        doc = load(".github/workflows/store-stills.yml")
        cls.inputs = doc["on"]["workflow_call"]["inputs"]
        cls.selector = doc["jobs"]["stills"]["runs-on"]

    def select(self, value: object, event: str = "pull_request") -> object:
        return evaluate(self.selector, {"inputs.runs-on": value, "github.event_name": event})

    def test_omitted_input_keeps_the_standard_default(self) -> None:
        self.assertEqual(self.inputs["runs-on"]["type"], "string")
        self.assertEqual(self.inputs["runs-on"]["default"], "sylphx-linux-standard")
        for event in EVENTS:
            with self.subTest(event=event):
                self.assertEqual(self.select(self.inputs["runs-on"]["default"], event), "sylphx-linux-standard")

    def test_supported_selections_resolve_to_the_literal_standard_label(self) -> None:
        # Empty kept the default before this change; GitHub compares strings case-insensitively.
        for value in ("", "sylphx-linux-standard", "Sylphx-Linux-Standard"):
            for event in EVENTS:
                with self.subTest(value=value, event=event):
                    self.assertEqual(self.select(value, event), "sylphx-linux-standard")

    def test_unknown_selections_fail_while_runs_on_is_evaluated(self) -> None:
        for value in ("sylphx-linux-xlarge", "sylphx-linux-2xlarge", "sylphx-linux-large", "sylphx-linux-control",
                      "sylphx-linux-standard-merge", "sylphx-linux-xlarge-merge", "ubuntu-latest", "macos-latest",
                      "self-hosted", " sylphx-linux-standard", "sylphx-linux-standard ", '"sylphx-linux-standard"',
                      '["self-hosted", "sylphx"]', "null", "{0}", "x' || 'sylphx-linux-standard"):
            for event in EVENTS:
                with self.subTest(value=value, event=event), self.assertRaises(Rejected):
                    self.select(value, event)

    def test_the_rejection_argument_is_never_json(self) -> None:
        # The refusal must not depend on the caller's text: no JSON value starts with `unsupported`
        # (GitHub's Newtonsoft reader takes a leading `u` only as `undefined`).
        self.assertIn("fromJSON(format('unsupported runs-on {0}', inputs.runs-on))", self.selector)
        with self.assertRaises(ValueError):
            json.JSONDecoder().raw_decode("unsupported runs-on sylphx-linux-standard")

    def test_evaluator_negative_controls(self) -> None:
        # The old passthrough accepted any caller label; the evaluator must show that.
        old = "${{ inputs.runs-on || 'sylphx-linux-standard' }}"
        self.assertEqual(evaluate(old, {"inputs.runs-on": "ubuntu-latest"}), "ubuntu-latest")
        self.assertEqual(evaluate(old, {"inputs.runs-on": ""}), "sylphx-linux-standard")
        with self.assertRaises(Rejected):
            evaluate("${{ fromJSON('') }}", {})
        self.assertEqual(evaluate("${{ 'a' && 'b' || fromJSON('') }}", {}), "b")


if __name__ == "__main__":
    unittest.main()
