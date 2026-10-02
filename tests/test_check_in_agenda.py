from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import check_in_agenda as agenda


def connection(nodes, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def item(number=1, repo="AllenInstitute/example", visibility="PUBLIC"):
    return {
        "type": "ISSUE",
        "status": {
            "__typename": "ProjectV2ItemFieldSingleSelectValue",
            "field": {"id": "status"},
            "optionId": "check-in",
            "name": "Check-In",
        },
        "content": {
            "__typename": "Issue",
            "id": f"{repo}/{number}",
            "state": "OPEN",
            "number": number,
            "title": "Example issue",
            "repository": {"nameWithOwner": repo, "visibility": visibility},
            "assignees": connection([{"login": "someone"}]),
        },
    }


FIELD = {
    "id": "status",
    "name": "Status",
    "__typename": "ProjectV2SingleSelectField",
    "options": [{"id": "check-in", "name": "Check-In"}],
}


class FakeAPI:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def query(self, query, variables):
        self.calls.append((query, variables))
        return next(self.responses)


def project(fields, cursor=None):
    return {"organization": {"projectV2": {"id": "project", "fields": connection(fields, cursor)}}}


class SelectionTests(unittest.TestCase):
    def test_exact_status_only(self):
        self.assertTrue(agenda.qualifies(item(), "status", "check-in"))
        for name in ("check-in", "Check-in", "Check-In ", "In Progress"):
            candidate = item()
            candidate["status"]["name"] = name
            self.assertFalse(agenda.qualifies(candidate, "status", "check-in"))
        candidate["status"] = None
        self.assertFalse(agenda.qualifies(candidate, "status", "check-in"))
        candidate = item()
        candidate["status"]["optionId"] = "other-option"
        self.assertFalse(agenda.qualifies(candidate, "status", "check-in"))

    def test_open_issues_only(self):
        candidate = item()
        candidate["content"]["state"] = "CLOSED"
        self.assertFalse(agenda.qualifies(candidate, "status", "check-in"))
        for kind in ("PULL_REQUEST", "DRAFT_ISSUE"):
            candidate = item()
            candidate["type"] = kind
            candidate["content"] = {"__typename": "PullRequest" if kind == "PULL_REQUEST" else "DraftIssue"}
            self.assertFalse(agenda.qualifies(candidate, "status", "check-in"))

    def test_private_internal_or_unknown_visibility_blocks(self):
        for visibility in ("PRIVATE", "INTERNAL", None):
            with self.subTest(visibility=visibility), self.assertRaises(agenda.AgendaError) as error:
                agenda.qualifies(item(repo="hidden/sensitive", visibility=visibility), "status", "check-in")
            self.assertNotIn("hidden", str(error.exception))
            self.assertNotIn("sensitive", str(error.exception))

    def test_inaccessible_content_and_bad_state_block(self):
        for content in (None, {"__typename": "Issue", "state": None}):
            candidate = item()
            candidate["content"] = content
            with self.assertRaises(agenda.AgendaError):
                agenda.qualifies(candidate, "status", "check-in")
        candidate = item()
        candidate["status"]["field"] = {}
        with self.assertRaises(agenda.AgendaError):
            agenda.qualifies(candidate, "status", "check-in")

    def test_redacted_items_block_even_with_unreadable_status(self):
        for kind in ("ISSUE", "REDACTED", None):
            candidate = {"type": kind, "status": None, "content": None}
            with self.assertRaises(agenda.AgendaError):
                agenda.qualifies(candidate, "status", "check-in")


class PaginationTests(unittest.TestCase):
    def test_fields_items_and_assignees_paginate_across_repositories(self):
        first = item(2, "OtherOrg/other")
        first["content"]["assignees"] = connection([{"login": "z"}], "assignee-next")
        api = FakeAPI([
            project([], "field-next"),
            project([FIELD]),
            {"node": {"items": connection([first], "item-next")}},
            {"node": {"assignees": connection([{"login": "a"}])}},
            {"node": {"items": connection([item()])}},
        ])
        issues = agenda.collect_issues(api)
        self.assertEqual([issue["repository"]["nameWithOwner"] for issue in issues],
                         ["AllenInstitute/example", "OtherOrg/other"])
        self.assertEqual(issues[1]["logins"], ["a", "z"])
        self.assertEqual([call[1]["cursor"] for call in api.calls],
                         [None, "field-next", None, "assignee-next", "item-next"])

    def test_private_item_on_later_page_blocks_entire_agenda(self):
        api = FakeAPI([
            project([FIELD]),
            {"node": {"items": connection([item()], "next")}},
            {"node": {"items": connection([item(2, visibility="PRIVATE")])}},
        ])
        with self.assertRaises(agenda.AgendaError):
            agenda.collect_issues(api)

    def test_invalid_or_repeating_pagination_blocks(self):
        for fetch in (lambda _: None, lambda _: {"nodes": []},
                      lambda _: connection([], "repeated")):
            with self.assertRaises(agenda.AgendaError):
                list(agenda.pages(fetch))

    def test_missing_status_wrong_type_and_missing_option_are_clear(self):
        for fields, message in (
            ([], "Status"),
            ([dict(FIELD, __typename="ProjectV2Field")], "single-select"),
            ([dict(FIELD, options=[])], "Check-In"),
            ([FIELD, FIELD], "Status"),
        ):
            with self.assertRaisesRegex(agenda.AgendaError, message):
                agenda.project_schema(FakeAPI([project(fields)]))

    def test_missing_project_blocks(self):
        with self.assertRaisesRegex(agenda.AgendaError, "Project #66"):
            agenda.project_schema(FakeAPI([{"organization": None}]))


class FormattingTests(unittest.TestCase):
    now = datetime(2026, 7, 6, 16, tzinfo=timezone.utc)

    def test_markdown_html_newlines_and_links_are_safe(self):
        issue = item()["content"]
        issue["title"] = '[Click](javascript:bad) *bold* <img src=x>\n# heading `code` &'
        issue["logins"] = ["someone"]
        draft = agenda.render([issue], self.now)
        self.assertIn(r"\[Click\]\(javascript:bad\)", draft)
        self.assertIn(r"\*bold\*", draft)
        self.assertIn("&lt;img src=x&gt;", draft)
        self.assertNotIn("\n# heading", draft)
        self.assertIn("https://github.com/AllenInstitute/example/issues/1", draft)
        self.assertIn(r"AllenInstitute/example/\#1", draft)
        self.assertIn("Assignees: @someone", draft)

    def test_empty_unassigned_and_stable_local_date(self):
        self.assertIn("No check-in items", agenda.render([], self.now))
        issue = item()["content"]
        issue["logins"] = []
        self.assertIn("Unassigned", agenda.render([issue], self.now))
        self.assertEqual(agenda.render([], self.now),
                         agenda.render([], self.now.replace(hour=20)))
        midnight_utc = datetime(2026, 7, 7, 0, tzinfo=timezone.utc)
        self.assertIn("Meeting: 2026-07-06", agenda.render([], midnight_utc))

    def test_invalid_link_reference_blocks(self):
        issue = item(repo="evil/repo)")["content"]
        issue["logins"] = []
        with self.assertRaises(agenda.AgendaError):
            agenda.render([issue], self.now)


class ScheduleTests(unittest.TestCase):
    def test_winter_summer_and_dst_transition_mondays(self):
        for date, hour in (("2026-01-05", 17), ("2026-07-06", 16),
                           ("2026-03-02", 17), ("2026-03-09", 16),
                           ("2026-10-26", 16), ("2026-11-02", 17)):
            now = datetime.fromisoformat(f"{date}T{hour}:00:00+00:00")
            correct = f"0 {hour} * * 1"
            wrong = f"0 {33 - hour} * * 1"
            self.assertTrue(agenda.schedule_due(correct, now), date)
            self.assertFalse(agenda.schedule_due(wrong, now), date)
            self.assertTrue(agenda.schedule_due(correct, now.replace(hour=hour + 2)), date)
            self.assertFalse(agenda.schedule_due(correct, now.replace(hour=hour - 1)), date)

    def test_other_days_and_after_midnight_skip(self):
        for timestamp in ("2026-07-05T16:00:00+00:00", "2026-07-07T07:00:00+00:00"):
            self.assertFalse(agenda.schedule_due("0 16 * * 1", datetime.fromisoformat(timestamp)))


class Response(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(json.dumps(payload).encode())
        self.headers = headers or {}


class APITests(unittest.TestCase):
    def test_request_uses_separate_project_credential(self):
        with patch.object(agenda, "urlopen", return_value=Response({"data": {}})) as opener:
            agenda.GitHub("synthetic-project-credential").query("query", {})
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"),
                         "Bearer " + "synthetic-project-credential")
        self.assertEqual(request.full_url, "https://api.github.com/graphql")

    def test_graphql_partial_data_is_rejected_without_logging_payload(self):
        api = agenda.GitHub("fake-token")
        with patch.object(agenda, "urlopen", return_value=Response({
            "data": {"secret": "sensitive-title"}, "errors": [{"message": "sensitive-title"}],
        })), self.assertRaises(agenda.AgendaError) as error:
            api.query("query", {})
        self.assertNotIn("sensitive-title", str(error.exception))
        self.assertNotIn("fake-token", str(error.exception))

    def test_rate_limit_retries_and_honors_reset(self):
        waits = []
        api = agenda.GitHub("fake-token", sleep=waits.append, clock=lambda: 100)
        responses = [
            Response({"errors": [{"type": "RATE_LIMITED"}]},
                     {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "115"}),
            Response({"data": {"ok": True}}),
        ]
        with patch.object(agenda, "urlopen", side_effect=responses):
            self.assertEqual(api.query("query", {}), {"ok": True})
        self.assertEqual(waits, [15])

    def test_http_rate_limit_and_transient_network_error_retry(self):
        waits = []
        api = agenda.GitHub("fake-token", sleep=waits.append)
        error = HTTPError("https://api.github.com/graphql", 429, "hidden", {"Retry-After": "7"}, None)
        with patch.object(agenda, "urlopen", side_effect=[
            error, URLError("sensitive"), Response({"data": {"ok": True}}),
        ]):
            self.assertEqual(api.query("query", {}), {"ok": True})
        self.assertEqual(waits, [7, 4])

    def test_retries_are_bounded(self):
        waits = []
        api = agenda.GitHub("fake-token", sleep=waits.append)
        with patch.object(agenda, "urlopen", side_effect=URLError("sensitive")) as opener:
            with self.assertRaisesRegex(agenda.AgendaError, "retries exhausted"):
                api.query("query", {})
        self.assertEqual(opener.call_count, 5)
        self.assertEqual(waits, [2, 4, 8, 16])

    def test_secondary_rate_limit_without_headers_retries(self):
        waits = []
        api = agenda.GitHub("fake-token", sleep=waits.append)
        body = io.BytesIO(json.dumps({"message": "You have exceeded a secondary rate limit."}).encode())
        error = HTTPError("https://api.github.com/graphql", 403, "hidden", {}, body)
        with patch.object(agenda, "urlopen", side_effect=[error, Response({"data": {}})]):
            self.assertEqual(api.query("query", {}), {})
        self.assertEqual(waits, [60])

    def test_long_rate_wait_fails_without_sleeping(self):
        api = agenda.GitHub("fake-token", sleep=lambda _: self.fail("should not wait"))
        with patch.object(agenda, "urlopen", return_value=Response(
            {"errors": [{"type": "RATE_LIMITED"}]}, {"Retry-After": "3600"},
        )), self.assertRaises(agenda.AgendaError):
            api.query("query", {})

    def test_cli_without_token_preserves_placeholder_and_logs_no_content(self):
        root = Path(__file__).resolve().parents[1]
        before = (root / "email.md").read_bytes()
        result = subprocess.run(
            [sys.executable, str(root / "scripts/check_in_agenda.py"), "--dry-run"],
            env={}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("PROJECT_READ_TOKEN", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual((root / "email.md").read_bytes(), before)

    def test_generation_dry_run_is_stable_and_failure_preserves_existing_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            issue = item()["content"]
            issue["logins"] = ["someone"]
            with patch.object(agenda, "__file__", str(root / "scripts/check_in_agenda.py")), \
                 patch.object(sys, "argv", ["check_in_agenda.py", "--dry-run"]), \
                 patch.object(agenda, "GitHub"), \
                 patch.object(agenda, "collect_issues", return_value=[issue]), \
                 patch("sys.stdout", new_callable=io.StringIO) as output:
                agenda.main()
                destination = root / "email.md"
                first = destination.read_bytes()
                mtime = destination.stat().st_mtime_ns
                agenda.main()
                self.assertEqual(destination.read_bytes(), first)
                self.assertEqual(destination.stat().st_mtime_ns, mtime)
                self.assertNotIn(issue["title"], output.getvalue())
                with patch.object(agenda, "collect_issues", side_effect=agenda.AgendaError("blocked")), \
                     patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                    agenda.main()
                self.assertEqual(destination.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
