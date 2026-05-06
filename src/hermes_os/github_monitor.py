"""GitHub Webhook Receiver + Hermes OS Event Bridge.

Receives GitHub webhooks (PR, push, issue) → publishes to EventBus.
ProactiveEngine subscribes to these events and triggers autonomous actions.

FastAPI server on port 8089. Register this as a GitHub webhook endpoint:
  POST /webhook/github
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from enum import Enum
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

from hermes_os.event_loop import Event, EventType, get_event_bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GitHub event → internal event mapping
# ---------------------------------------------------------------------------


class GitHubEventType(str, Enum):
    PULL_REQUEST = "pull_request"
    PUSH = "push"
    ISSUES = "issues"
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST_REVIEW = "pull_request_review"
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"
    CHECK_RUN = "check_run"
    CHECK_SUITE = "check_suite"
    RELEASE = "release"


# Map GitHub event → our internal event
_GITHUB_TO_INTERNAL = {
    "pull_request": EventType.PULL_REQUEST_OPENED,  # overridden per action below
    "push": EventType.PUSH,
    "issues": EventType.ISSUE_OPENED,  # overridden per action below
    "issue_comment": EventType.ISSUE_COMMENT,
    "pull_request_review": EventType.PULL_REQUEST_REVIEW,
    "pull_request_review_comment": EventType.PULL_REQUEST_REVIEW_COMMENT,
}


# ---------------------------------------------------------------------------
# Pydantic models for webhook payloads
# ---------------------------------------------------------------------------


class GitHubUser(BaseModel):
    login: str
    id: int
    avatar_url: str | None = None


class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    description: str | None
    html_url: str
    language: str | None
    stargazers_count: int = 0
    forks_count: int = 0


class PullRequestPayload(BaseModel):
    action: str  # opened, closed, merged, review_requested, etc.
    number: int
    title: str
    body: str | None
    state: str
    merged: bool | None
    user: GitHubUser
    repo: GitHubRepository
    pr: dict[str, Any] = {}
    diff_url: str
    html_url: str
    base: dict[str, Any] = {}  # base branch info
    head: dict[str, Any] = {}  # head branch info
    requested_reviewers: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []


class PushPayload(BaseModel):
    ref: str  # refs/heads/main
    before: str
    after: str
    repository: GitHubRepository
    pusher: dict[str, Any]
    commits: list[dict[str, Any]]
    head_commit: dict[str, Any] | None
    forced: bool
    created: bool
    deleted: bool


class IssuePayload(BaseModel):
    action: str  # opened, closed, reopened, etc.
    issue: dict[str, Any]
    changes: dict[str, Any] = {}
    user: GitHubUser
    repo: GitHubRepository
    label: str | None = None  # set if action=labeled


# ---------------------------------------------------------------------------
# GitHub webhook verifier
# ---------------------------------------------------------------------------

_GITHUB_WEBHOOK_SECRET = os.environ.get("HERMES_GITHUB_WEBHOOK_SECRET", "")


def verify_github_signature(
    body: bytes, signature: str | None, secret: str = _GITHUB_WEBHOOK_SECRET
) -> bool:
    """Verify X-Hub-Signature-256 header against the raw request body."""
    if not signature or not secret:
        return True  # Skip verification if no secret configured (dev mode)
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Event transformers: GitHub payload → Hermes OS Event
# ---------------------------------------------------------------------------


def pr_to_event(action: str, payload: dict[str, Any]) -> Event | None:
    """Map GitHub pull_request event action to appropriate Hermes OS event."""
    repo = payload.get("repository", {})
    pr = payload.get("pull_request", {})

    base_event_type: EventType | None = None
    if action == "opened":
        base_event_type = EventType.PULL_REQUEST_OPENED
    elif action == "closed":
        if pr.get("merged"):
            base_event_type = EventType.PULL_REQUEST_MERGED
        else:
            base_event_type = EventType.PULL_REQUEST_CLOSED
    elif action == "reopened":
        base_event_type = EventType.PULL_REQUEST_REOPENED
    elif action == "review_requested":
        base_event_type = EventType.PULL_REQUEST_REVIEW_REQUESTED
    elif action == "synchronize":
        base_event_type = EventType.PULL_REQUEST_SYNCED
    else:
        return None  # Ignore other actions (labeled, assigned, etc.)

    return Event(
        type=base_event_type,
        payload={
            "repo": repo.get("full_name", ""),
            "repo_url": repo.get("html_url", ""),
            "pr_number": payload.get("number", 0),
            "pr_title": pr.get("title", ""),
            "pr_body": pr.get("body", "") or "",
            "pr_user": payload.get("pull_request", {}).get("user", {}).get("login", ""),
            "pr_state": pr.get("state", "open"),
            "pr_merged": pr.get("merged", False),
            "pr_url": payload.get("pull_request", {}).get("html_url", ""),
            "pr_diff_url": payload.get("pull_request", {}).get("diff_url", ""),
            "base_branch": pr.get("base", {}).get("ref", ""),
            "head_branch": pr.get("head", {}).get("ref", ""),
            "changed_files": pr.get("changed_files", 0),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "labels": [l.get("name", "") for l in pr.get("labels", [])],
            "requested_reviewers": [r.get("login", "") for r in pr.get("requested_reviewers", [])],
            "action": action,
            "raw": payload,
        },
        source="github",
    )


def push_to_event(payload: dict[str, Any]) -> Event:
    """Map GitHub push event to Hermes OS event."""
    repo = payload.get("repository", {})
    head_commit = payload.get("head_commit") or {}
    commits = payload.get("commits", [])

    # Extract branch from ref (refs/heads/main → main)
    branch = ""
    ref = payload.get("ref", "")
    if ref.startswith("refs/heads/"):
        branch = ref[len("refs/heads/") :]

    return Event(
        type=EventType.PUSH,
        payload={
            "repo": repo.get("full_name", ""),
            "repo_url": repo.get("html_url", ""),
            "branch": branch,
            "before": payload.get("before", ""),
            "after": payload.get("after", ""),
            "head_commit_sha": head_commit.get("id", ""),
            "head_commit_message": head_commit.get("message", ""),
            "head_commit_author": head_commit.get("author", {}).get("name", ""),
            "forced": payload.get("forced", False),
            "created": payload.get("created", False),
            "deleted": payload.get("deleted", False),
            "commit_count": len(commits),
            "pusher": payload.get("pusher", {}).get("name", ""),
            "commits_summary": (f"{len(commits)} commit(s)" if commits else "no commits"),
            "raw": payload,
        },
        source="github",
    )


def issue_to_event(action: str, payload: dict[str, Any]) -> Event | None:
    """Map GitHub issues event action to Hermes OS event."""
    repo = payload.get("repository", {})
    issue = payload.get("issue", {})

    if action == "opened":
        event_type = EventType.ISSUE_OPENED
    elif action == "closed":
        event_type = EventType.ISSUE_CLOSED
    elif action == "reopened":
        event_type = EventType.ISSUE_REOPENED
    elif action == "labeled":
        label_name = ""
        labels = issue.get("labels", []) or []
        if payload.get("label"):
            label_name = payload.get("label", {}).get("name", "")
        elif labels:
            label_name = labels[-1].get("name", "")
        event_type = EventType.ISSUE_LABELED
    else:
        return None

    return Event(
        type=event_type,
        payload={
            "repo": repo.get("full_name", ""),
            "repo_url": repo.get("html_url", ""),
            "issue_number": issue.get("number", 0),
            "issue_title": issue.get("title", ""),
            "issue_body": issue.get("body", "") or "",
            "issue_state": issue.get("state", "open"),
            "issue_user": issue.get("user", {}).get("login", ""),
            "issue_url": issue.get("html_url", ""),
            "labels": [l.get("name", "") for l in issue.get("labels", [])],
            "assignees": [a.get("login", "") for a in issue.get("assignees", [])],
            "action": action,
            "raw": payload,
        },
        source="github",
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Hermes OS GitHub Monitor", version="1.0.0")

# Store monitored repos in memory (loaded from env on startup)
_MONITORED_REPOS: list[str] = []


def load_monitored_repos() -> None:
    global _MONITORED_REPOS
    env_val = os.environ.get("HERMES_MONITORED_REPOS", "")
    if env_val:
        _MONITORED_REPOS = [r.strip() for r in env_val.split(",") if r.strip()]
    else:
        # Default: monitor hermes-os and blend
        _MONITORED_REPOS = ["jajabong/hermes-os", "jajabong/blend"]


load_monitored_repos()


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe for the webhook server."""
    return {
        "status": "ok",
        "monitored_repos": _MONITORED_REPOS,
        "event_bus_handlers": len(get_event_bus()._handlers),
    }


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    response: Response,
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
) -> dict[str, str]:
    """Receive and process GitHub webhook, publish Hermes OS events."""
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    if not verify_github_signature(body, x_hub_signature_256):
        logger.warning("GitHub webhook signature verification failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    if not x_github_event:
        response.status_code = 204
        return {}

    event_name = x_github_event.lower()

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Ignore some noise events
    if event_name in ("ping", "meta", "github_app_authorization"):
        logger.info("GitHub ping/event: %s", event_name)
        response.status_code = 200
        return {"status": "ok", "event": event_name}

    # Route to appropriate transformer
    event: Event | None = None

    if event_name == "pull_request":
        action = payload.get("action", "")
        event = pr_to_event(action, payload)
    elif event_name == "push":
        event = push_to_event(payload)
    elif event_name in ("issues", "issue_comment"):
        action = payload.get("action", "")
        event = issue_to_event(action, payload)
    elif event_name in (
        "check_run",
        "check_suite",
        "release",
        "pull_request_review",
        "pull_request_review_comment",
    ):
        # Forward but don't transform — let handlers deal with raw payload
        repo = payload.get("repository", {}).get("full_name", "")
        event = Event(
            type=EventType(event_name),
            payload={"repo": repo, "raw": payload, "action": payload.get("action", "")},
            source="github",
        )

    if event is None:
        # Unsupported or ignored action
        response.status_code = 200
        return {"status": "ignored", "event": event_name}

    # Check if this repo is monitored
    repo_name = event.payload.get("repo", "")
    if _MONITORED_REPOS and repo_name not in _MONITORED_REPOS:
        logger.debug("Repo %s not in monitored list, ignoring", repo_name)
        response.status_code = 200
        return {"status": "ignored", "repo": repo_name}

    # Publish to EventBus (non-blocking from webhook perspective)
    asyncio.create_task(get_event_bus().publish(event))

    logger.info(
        "GitHub webhook published: event=%s repo=%s id=%s delivery=%s",
        event.type.value if hasattr(event.type, "value") else event.type,
        repo_name,
        x_github_delivery or "unknown",
        event_name,
    )

    response.status_code = 200
    return {"status": "ok", "event": event_name, "delivery": x_hub_signature_256}


# ---------------------------------------------------------------------------
# Standalone runner (for development / testing)
# ---------------------------------------------------------------------------


def run_server(port: int = 8089) -> None:
    import uvicorn

    logger.info(
        "Starting GitHub webhook server on port %d, monitored repos: %s",
        port,
        _MONITORED_REPOS,
    )
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run_server()
