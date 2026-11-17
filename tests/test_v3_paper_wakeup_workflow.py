"""Static regression guard for the PAPER fallback trigger (stdlib only)."""
import unittest
from pathlib import Path


class PaperWakeupWorkflow(unittest.TestCase):
    def test_trusted_v2_completion_is_fallback_trigger(self):
        workflow = Path(".github/workflows/v3_paper.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn("workflows: ['Research V2 sampled tape and immutable evidence']", workflow)
        self.assertIn("types: [completed]", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("Verify persisted remote state and chain", workflow)


if __name__ == "__main__":
    unittest.main()
