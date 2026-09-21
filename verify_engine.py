"""
NoulGate Engine Verification
=============================
Tests the core engine against 8 prompts spanning all domains.
Confirms: imports work, Jev API responds, pruning logic routes correctly.

Run with:
    uv run python verify_engine.py
"""

from dotenv import load_dotenv

load_dotenv()

from noulgate import NoulGateEngine, ToolDefinition  # noqa: E402

# ---------------------------------------------------------------------------
# Build a realistic 10-tool registry across 4 domains
# ---------------------------------------------------------------------------

TOOLS = [
    # database
    ToolDefinition(
        name="sql_query_runner",
        description="Executes a read-only SQL query against the Postgres production database.",
        parameters={"query": {"type": "string", "description": "SQL SELECT statement"}},
        domain="database",
    ),
    ToolDefinition(
        name="db_schema_inspector",
        description="Returns the columns, types, and indexes for a given database table.",
        parameters={"table_name": {"type": "string"}},
        domain="database",
    ),
    # github
    ToolDefinition(
        name="github_get_pr",
        description="Fetches a pull request's diff, comments, and CI build status from GitHub.",
        parameters={"pr_number": {"type": "integer"}},
        domain="github",
    ),
    ToolDefinition(
        name="github_search_issues",
        description="Searches GitHub issues and bug reports by keyword.",
        parameters={"query": {"type": "string"}},
        domain="github",
    ),
    # filesystem
    ToolDefinition(
        name="fs_read_file",
        description="Reads the full contents of a local file by path.",
        parameters={"path": {"type": "string"}},
        domain="filesystem",
    ),
    ToolDefinition(
        name="fs_search_files",
        description="Searches for files matching a glob pattern across the workspace.",
        parameters={"pattern": {"type": "string"}},
        domain="filesystem",
    ),
    # web_search
    ToolDefinition(
        name="web_search",
        description="Searches the live internet for current news, articles, and events.",
        parameters={"query": {"type": "string"}},
        domain="web_search",
    ),
    ToolDefinition(
        name="web_scrape",
        description="Downloads and extracts clean text from a specific URL.",
        parameters={"url": {"type": "string"}},
        domain="web_search",
    ),
    # slack
    ToolDefinition(
        name="slack_post_message",
        description="Posts a message or alert to an internal Slack channel.",
        parameters={"channel": {"type": "string"}, "message": {"type": "string"}},
        domain="slack",
    ),
    ToolDefinition(
        name="slack_get_channel_history",
        description="Retrieves the last N messages from a Slack channel.",
        parameters={"channel": {"type": "string"}, "limit": {"type": "integer"}},
        domain="slack",
    ),
]

DOMAIN_CRITERIA = {
    "database":   "SQL queries, Postgres, database tables, revenue, user counts, analytics",
    "github":     "Pull requests, code reviews, GitHub issues, diffs, CI status",
    "filesystem": "Reading files, finding files, local disk, code search, workspace",
    "web_search": "Live internet, current events, news, URLs, web pages",
    "slack":      "Sending messages, Slack channels, team alerts, chat notifications",
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

engine = NoulGateEngine(tool_threshold=0.40)
engine.register_many(TOOLS, domain_criteria=DOMAIN_CRITERIA)

PROMPTS = [
    ("casual",      "Hey! Can you explain the difference between TCP and UDP?"),
    ("casual",      "Thanks, that makes sense!"),
    ("database",    "What was our total revenue from transactions last week?"),
    ("database",    "Show me the columns in the users table."),
    ("github",      "Is PR #42 ready to merge? Are CI checks passing?"),
    ("filesystem",  "What is in the file src/noulgate/engine.py?"),
    ("web_search",  "What are the latest AI announcements this week?"),
    ("slack",       "Post a message to #deployments saying v1.2 is live."),
]

print("=" * 72)
print("  NoulGate Engine — Verification Run")
print(f"  Tools registered: {len(TOOLS)} across {len(DOMAIN_CRITERIA)} domains")
print("=" * 72)

passed = 0
failed = 0

for expected_domain, prompt in PROMPTS:
    result = engine.prune(prompt)

    # Check routing correctness
    if expected_domain == "casual":
        ok = not result.needs_tool
    else:
        ok = result.needs_tool and result.selected_domain == expected_domain

    status = "✅ PASS" if ok else "❌ FAIL"
    if ok:
        passed += 1
    else:
        failed += 1

    print(f"\n{status}  [{expected_domain.upper()}]")
    print(f"   Prompt  : {prompt!r}")
    print(f"   {result.summary()}")

print("\n" + "=" * 72)
print(f"  Results: {passed} passed / {failed} failed / {len(PROMPTS)} total")
print("=" * 72)
