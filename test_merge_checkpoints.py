import json
import tempfile
import unittest
from pathlib import Path

import agent
import merge_checkpoints


class MergeCheckpointTests(unittest.TestCase):
    def test_resolved_result_wins_over_stale_pending_row(self):
        resolved = {"algo_version": agent.ALGO_VERSION, "physician_search_version": agent.PHYSICIAN_SEARCH_VERSION, "name": "דוד כהן", "category": "family_doctor", "status": "NO_VERIFIED_PUBLIC_EMAIL", "attempted_urls": '["https://a.example"]'}
        pending = {"algo_version": agent.ALGO_VERSION, "physician_search_version": agent.PHYSICIAN_SEARCH_VERSION, "name": "דוד כהן", "category": "family_doctor", "status": "PENDING_SEARCH_PROVIDER", "attempted_urls": '["https://b.example"]'}
        merged = merge_checkpoints.combine(resolved, pending)
        self.assertEqual("NO_VERIFIED_PUBLIC_EMAIL", merged["status"])
        self.assertEqual(["https://a.example", "https://b.example"], json.loads(merged["attempted_urls"]))

    def test_verified_result_is_never_replaced_by_no_email(self):
        verified = {"algo_version": agent.ALGO_VERSION, "name": "שרה לוי", "category": "doula", "status": "VERIFIED", "email": "sara@example.org", "confidence": 90}
        empty = {"algo_version": agent.ALGO_VERSION, "name": "שרה לוי", "category": "doula", "status": "NO_VERIFIED_PUBLIC_EMAIL"}
        self.assertEqual("VERIFIED", merge_checkpoints.combine(verified, empty)["status"])


if __name__ == "__main__":
    unittest.main()
