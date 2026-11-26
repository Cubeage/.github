"""Protect the reusable Keel pin check's caller contract."""
import pathlib
import unittest

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/keel-pin-check.yml"


class KeelPinCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # PyYAML's SafeLoader treats the Actions key 'on' as a YAML 1.1 boolean.
        cls.doc = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def test_call_requires_only_the_two_reader_secrets(self) -> None:
        # The caller controls events. This is a verdict-only check with no inputs or outputs.
        self.assertEqual(self.doc["on"], {"workflow_call": {"secrets": {
            "CUBEAGE_CI_READER_APP_ID": {"required": "true"},
            "CUBEAGE_CI_READER_APP_KEY": {"required": "true"},
        }}})

    def test_caller_checkout_is_read_only_and_preserves_the_parent(self) -> None:
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        jobs = self.doc["jobs"]
        self.assertEqual(set(jobs), {"keel-pin-check"})
        job = jobs["keel-pin-check"]
        self.assertNotIn("permissions", job)
        self.assertNotIn("if", job)
        self.assertNotIn("continue-on-error", job)
        self.assertEqual(
            job["runs-on"],
            "${{ github.event_name == 'merge_group' && 'sylphx-linux-standard-merge' || 'sylphx-linux-standard' }}",
        )
        checkout, check = job["steps"]
        self.assertRegex(checkout["uses"], r"^actions/checkout@[0-9a-f]{40}$")
        self.assertRegex(check["uses"], r"^SylphxAI/\.github/\.github/actions/keel-pin-check@[0-9a-f]{40}$")
        self.assertEqual(checkout["with"], {"persist-credentials": "false", "fetch-depth": "2"})
        self.assertNotIn("if", check)
        self.assertNotIn("continue-on-error", check)

    def test_pin_check_uses_the_caller_event_and_explicit_secrets(self) -> None:
        self.assertEqual(self.doc["jobs"]["keel-pin-check"]["steps"][1]["with"], {
            "reader-app-id": "${{ secrets.CUBEAGE_CI_READER_APP_ID }}",
            "reader-app-key": "${{ secrets.CUBEAGE_CI_READER_APP_KEY }}",
            "base": "${{ (github.event_name == 'pull_request' || github.event_name == 'merge_group') && 'auto' || '' }}",
        })
