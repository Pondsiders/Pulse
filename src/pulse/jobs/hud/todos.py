"""Todoist gathering for HUD - fetches tasks from Todoist REST API."""

import json
import os
import urllib.request

import logfire

API_BASE = "https://api.todoist.com/rest/v2"

# Projects to show in HUD, grouped by owner
# Order matters: displayed in this sequence
HUD_PROJECTS = [
    ("Pondside", "Pondside"),   # (display name, match string)
    ("Jeffery", "Jeffery"),
    ("Alpha", "Alpha"),
]


def get_token() -> str | None:
    """Get Todoist API token from environment."""
    return os.environ.get("TODOIST_TOKEN")


def api_request(endpoint: str, token: str) -> dict | list | None:
    """Make a Todoist API request."""
    url = f"{API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logfire.error("Failed to fetch from Todoist", endpoint=endpoint, error=str(e))
        return None


def format_priority(p: int) -> str:
    """Convert API priority (4=urgent) to display format."""
    return {4: "[p1]", 3: "[p2]", 2: "[p3]"}.get(p, "")


def format_task(task: dict) -> str:
    """Format a single task for display."""
    priority = format_priority(task.get("priority", 1))
    content = task["content"]

    if priority:
        return f"• {priority} {content}"
    else:
        return f"• {content}"


def gather_todos() -> str | None:
    """Gather Todoist tasks for HUD display, grouped by project."""
    token = get_token()
    if not token:
        logfire.warn("TODOIST_TOKEN not set, skipping todos")
        return None

    # Get all projects to map IDs to names
    projects = api_request("/projects", token)
    if not projects:
        return None

    # Build mapping: project_id -> display_name for HUD projects
    project_to_display = {}
    for p in projects:
        for display_name, match_string in HUD_PROJECTS:
            if match_string.lower() in p["name"].lower():
                project_to_display[p["id"]] = display_name
                break

    # Get all tasks
    tasks = api_request("/tasks", token)
    if not tasks:
        return None

    # Group tasks by project
    tasks_by_project = {display_name: [] for display_name, _ in HUD_PROJECTS}

    for task in tasks:
        project_id = task.get("project_id")
        if project_id in project_to_display:
            display_name = project_to_display[project_id]
            tasks_by_project[display_name].append(task)

    # Sort each project's tasks by priority (high first)
    for project_tasks in tasks_by_project.values():
        project_tasks.sort(key=lambda t: -t.get("priority", 1))

    # Format output
    lines = []
    for display_name, _ in HUD_PROJECTS:
        project_tasks = tasks_by_project[display_name]
        if project_tasks:
            lines.append(f"*{display_name}*")
            for task in project_tasks:
                lines.append(format_task(task))

    if not lines:
        return "No tasks"

    return "\n".join(lines)
