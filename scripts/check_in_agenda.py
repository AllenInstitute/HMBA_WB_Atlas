"""Generate a public-safe draft from organization ProjectV2 #66; never send mail."""

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


LA = ZoneInfo("America/Los_Angeles")
PROJECT_QUERY = """
query($cursor: String) {
  organization(login: "AllenInstitute") {
    projectV2(number: 66) {
      id
      fields(first: 100, after: $cursor) {
        nodes {
          __typename
          ... on ProjectV2SingleSelectField { id name options { id name } }
          ... on ProjectV2Field { id name }
          ... on ProjectV2IterationField { id name }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
ITEMS_QUERY = """
query($id: ID!, $cursor: String) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        nodes {
          type
          status: fieldValueByName(name: "Status") {
            __typename
            ... on ProjectV2ItemFieldSingleSelectValue {
              optionId name field { ... on ProjectV2SingleSelectField { id } }
            }
          }
          content {
            __typename
            ... on Issue {
              id title number state
              repository { nameWithOwner visibility }
              assignees(first: 100) {
                nodes { login }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
ASSIGNEES_QUERY = """
query($id: ID!, $cursor: String) {
  node(id: $id) {
    ... on Issue {
      assignees(first: 100, after: $cursor) {
        nodes { login }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class AgendaError(Exception):
    pass


class GitHub:
    def __init__(self, token, sleep=time.sleep, clock=time.time):
        if not token:
            raise AgendaError("Set PROJECT_READ_TOKEN with organization Projects read access.")
        self.token = token
        self.sleep = sleep
        self.clock = clock

    def query(self, query, variables):
        request = Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "User-Agent": "HMBA-check-in-agenda",
            },
        )
        for attempt in range(5):
            headers = {}
            retry = False
            rate_message = False
            try:
                with urlopen(request, timeout=60) as response:
                    headers = response.headers
                    payload = json.load(response)
                errors = payload.get("errors")
                if not errors and isinstance(payload.get("data"), dict):
                    return payload["data"]
                retry = bool(errors) and all(
                    error.get("type") == "RATE_LIMITED"
                    or error.get("extensions", {}).get("code") == "RATE_LIMITED"
                    or any(
                        phrase in str(error.get("message", "")).lower()
                        for phrase in ("rate limit", "secondary rate", "temporarily unavailable")
                    )
                    for error in errors
                )
                rate_message = bool(errors) and any(
                    "secondary rate" in str(error.get("message", "")).lower()
                    for error in errors
                )
                if not retry:
                    raise AgendaError(
                        "GraphQL failed. Verify the token's organization Projects read "
                        "permission, SSO authorization, and access to project #66. "
                        "API details are withheld to protect project content."
                    )
            except HTTPError as error:
                headers = error.headers
                if error.code == 403:
                    try:
                        message = str(json.load(error).get("message", "")).lower()
                        rate_message = "rate limit" in message or "secondary rate" in message
                    except (ValueError, AttributeError):
                        pass
                retry = error.code in (429, 500, 502, 503, 504) or (
                    error.code == 403
                    and (
                        headers.get("Retry-After")
                        or headers.get("X-RateLimit-Remaining") == "0"
                        or rate_message
                    )
                )
                error.close()
                if not retry:
                    raise AgendaError(
                        "GitHub rejected the request. Check PROJECT_READ_TOKEN permissions "
                        "and organization SSO authorization; no API content was logged."
                    ) from None
            except (URLError, TimeoutError):
                retry = True
            if retry and attempt < 4:
                delay = max(
                    60 if rate_message else 2 ** (attempt + 1),
                    float(headers.get("Retry-After", 0)),
                    float(headers.get("X-RateLimit-Reset", 0)) - self.clock()
                    if headers.get("X-RateLimit-Remaining") == "0" else 0,
                )
                if delay > 600:
                    break
                self.sleep(delay)
                continue
            break
        raise AgendaError("GitHub retries exhausted or rate-limit wait exceeds 10 minutes. Retry later.")


def pages(fetch):
    cursor = None
    seen = set()
    while True:
        connection = fetch(cursor)
        if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
            raise AgendaError("Incomplete project response; refusing to generate a partial agenda.")
        yield from connection["nodes"]
        info = connection.get("pageInfo", {})
        if info.get("hasNextPage") is False:
            return
        cursor = info.get("endCursor")
        if info.get("hasNextPage") is not True or not cursor or cursor in seen:
            raise AgendaError("Invalid pagination; refusing to generate a partial agenda.")
        seen.add(cursor)


def project_schema(api):
    project_id = None

    def fetch(cursor):
        nonlocal project_id
        organization = api.query(PROJECT_QUERY, {"cursor": cursor}).get("organization")
        project = (organization or {}).get("projectV2")
        if not project or not project.get("id"):
            raise AgendaError("Project #66 is unavailable. Check organization Projects read access.")
        project_id = project["id"]
        return project.get("fields")

    fields = list(pages(fetch))
    status = [field for field in fields if field and field.get("name") == "Status"]
    if len(status) != 1 or status[0].get("__typename") != "ProjectV2SingleSelectField":
        raise AgendaError("Project #66 must have one single-select field named exactly Status.")
    options = [option for option in status[0]["options"] if option["name"] == "Check-In"]
    if len(options) != 1:
        raise AgendaError("Status must have one option named exactly Check-In.")
    return project_id, status[0]["id"], options[0]["id"]


def qualifies(item, field_id, option_id):
    """Keep selection separate so a future target-date filter can be added here."""
    if not isinstance(item, dict):
        raise AgendaError("Unreadable project item; refusing to generate a partial agenda.")
    if item.get("type") not in ("ISSUE", "PULL_REQUEST", "DRAFT_ISSUE") or (
        item["type"] == "ISSUE" and not item.get("content")
    ):
        raise AgendaError(
            "A project item is inaccessible or redacted, so selection cannot be verified. "
            "Grant read access to all source issues or use a private host; nothing was published."
        )
    status = item.get("status")
    if status is None:
        return False
    if status.get("__typename") != "ProjectV2ItemFieldSingleSelectValue":
        raise AgendaError("Unexpected Status field value; check the project schema.")
    if status.get("field", {}).get("id") != field_id:
        raise AgendaError("Status field identity cannot be verified; nothing was published.")
    if (
        status.get("optionId") != option_id
        or status.get("name") != "Check-In"
    ):
        return False
    if item.get("type") in ("PULL_REQUEST", "DRAFT_ISSUE"):
        return False
    content = item.get("content")
    if item.get("type") != "ISSUE" or not content or content.get("__typename") != "Issue":
        raise AgendaError(
            "A Check-In item's issue cannot be verified. Grant read access to all source "
            "issues or move this automation to a private repository; nothing was published."
        )
    if content.get("state") == "CLOSED":
        return False
    if content.get("state") != "OPEN":
        raise AgendaError("Issue state cannot be verified; nothing was published.")
    if (content.get("repository") or {}).get("visibility") != "PUBLIC":
        raise AgendaError(
            "An open Check-In issue has non-public or unverifiable repository visibility. "
            "Do not publish this agenda in a public repository. Use a private host with "
            "authorized readers for the full agenda; nothing was published."
        )
    return True


def collect_issues(api):
    project_id, field_id, option_id = project_schema(api)
    issues = {}
    for item in pages(
        lambda cursor: (api.query(ITEMS_QUERY, {"id": project_id, "cursor": cursor})
                        .get("node") or {}).get("items")
    ):
        if not qualifies(item, field_id, option_id):
            continue
        issue = dict(item["content"])
        first_page = issue.get("assignees")

        def fetch_assignees(cursor):
            if cursor is None:
                return first_page
            return (api.query(ASSIGNEES_QUERY, {"id": issue["id"], "cursor": cursor})
                    .get("node") or {}).get("assignees")

        issue["logins"] = sorted({node["login"] for node in pages(fetch_assignees)})
        issues[issue["id"]] = issue
    return sorted(issues.values(), key=lambda issue: (issue["repository"]["nameWithOwner"], issue["number"]))


def escape_markdown(text):
    text = " ".join(text.split())
    text = html.escape(text, quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", text)


def render(issues, now):
    date = now.astimezone(LA).date().isoformat()
    lines = [
        "# Check-in agenda draft", "",
        "To: nelson.johansen@alleninstitute.org",
        f"Subject: Check-in agenda — {date}",
        f"Meeting: {date}, 9:00 AM America/Los_Angeles", "",
        "Hi Nelson,", "",
        "Here are the open issues marked **Check-In** for our check-in:", "",
    ]
    for issue in issues:
        repo = issue["repository"]["nameWithOwner"]
        number = issue["number"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or (
            not isinstance(number, int) or number <= 0
        ):
            raise AgendaError("Invalid public issue reference; nothing was published.")
        assignees = ", ".join(escape_markdown("@" + login) for login in issue["logins"])
        lines.append(
            f"- [{escape_markdown(issue['title'])}](https://github.com/{repo}/issues/{number}) "
            f"— {escape_markdown(repo + '/#' + str(number))} "
            f"— Assignees: {assignees or 'Unassigned'}"
        )
    if not issues:
        lines.append("No check-in items: no open issues are currently marked **Check-In**.")
    lines.extend(["", "Please bring updates, blockers, or questions.", "", "Thanks!", "Nelson", ""])
    return "\n".join(lines)


def schedule_due(cron, now):
    local = now.astimezone(LA)
    expected = "0 16 * * 1" if local.utcoffset().total_seconds() == -7 * 3600 else "0 17 * * 1"
    return cron == expected and local.weekday() == 0 and local.hour >= 9


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-schedule", metavar="CRON")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    if args.check_schedule is not None:
        print("true" if schedule_due(args.check_schedule, now) else "false")
        return
    try:
        issues = collect_issues(GitHub(os.environ.get("PROJECT_READ_TOKEN")))
        draft = render(issues, now)
        destination = Path(__file__).resolve().parents[1] / "email.md"
        if not destination.exists() or destination.read_text(encoding="utf-8") != draft:
            destination.write_text(draft, encoding="utf-8")
        print("Draft validated locally; no email sent." if args.dry_run else "Draft generated; no email sent.")
    except AgendaError as error:
        print(f"Agenda generation failed: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Never expose API payloads or project content via a traceback.
        print("Agenda generation failed: unexpected or incomplete API data; nothing published.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
