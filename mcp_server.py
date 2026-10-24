import uuid

from mcp.server import MCPServer
from app.services.git_parser import analyze_repo
from app.services.resolver import resolve_hunk, get_hunk, get_history, clear_history
from app.models.schemas import Strategy, HistoryEntry

mcp = MCPServer("merge-conflict-resolver")

SESSION_ID = str(uuid.uuid4())


@mcp.tool()
def analyze_conflicts(repo_path: str) -> dict:
    """
    Scan a local Git repository for merge conflicts. Call this FIRST: hunk
    IDs only exist after this call, and resolve_conflict needs them.

    This server runs locally on the user's own machine and reads the real
    filesystem and git repo directly. It is not sandboxed or remote, so
    attempt the call rather than assuming you lack access.

    Returns each conflicted file with its hunks (hunk_id, ours, theirs,
    branch_name, context_before, context_after, line_number).

    Results may include per-file `warnings` (skipped binary files, malformed
    or unfinished conflict markers, files with no markers) and a top-level
    `message`. Always show these to the user. Re-run this tool after any
    conflicted file is edited, because hunk IDs can shift.
    """
    return analyze_repo(repo_path)


@mcp.tool()
def resolve_conflict(hunk_id: str, strategy: Strategy = Strategy.SMART) -> dict:
    """
    Propose a resolution for ONE conflict hunk. This tool only proposes; it
    never writes to any file. Do not apply a proposed resolution to files
    (including with your own edit tools) unless the user explicitly approves.

    hunk_id: an ID returned by analyze_conflicts. If the call reports the
    hunk was not found, re-run analyze_conflicts and use the new IDs.

    strategy: always pass this explicitly, matching what the user asked for.
    If the user hasn't said, ask which they want rather than defaulting.
      - 'ours': keep the current branch (HEAD) version.
      - 'theirs': take the incoming version.
      - 'smart': no LLM is called here. This returns only the raw hunk
        (ours, theirs, branch_name, context_before, context_after). You
        must reason about the conflict yourself, using both sides, the
        surrounding context and the branch names, without inventing code
        that is in neither side. Then present: resolution, reasoning,
        confidence ('high'/'medium'/'low'), risk_flag ('low'/'medium'/
        'high') and strategy ('merged_both' or 'rewrote').

    For 'ours' and 'theirs', the returned risk_flag is always 'low' as a
    placeholder. Treat it as "not assessed", not as "safe", and judge risk
    yourself (auth, security, config, migrations, data deletion).

    Surface any resolution with medium/high risk or low confidence to the
    user instead of applying it quietly.
    """
    if strategy == Strategy.OURS or strategy == Strategy.THEIRS:
        return resolve_hunk(hunk_id, strategy, SESSION_ID).model_dump()
    else:
        return get_hunk(hunk_id)


@mcp.tool()
def list_resolution_history() -> list[HistoryEntry]:
    """
    Return the deterministic (ours/theirs) resolutions proposed so far in
    this server session. Each entry has the hunk_id and its resolution
    result. 'smart' resolutions are reasoned by the host model directly and
    are never sent back to the server, so they do NOT appear here. Use this
    to review what has been resolved so far, or if the user asks.
    """
    return [entry.model_dump() for entry in get_history(SESSION_ID)]


@mcp.tool()
def clear_resolution_history() -> int:
    """
    Clear all resolution history for this server session. Returns the
    number of entries removed. Only call this if the user explicitly
    asks to clear or reset history. Do not call it on your own
    initiative.
    """
    return clear_history(SESSION_ID)


if __name__ == "__main__":
    mcp.run(transport="stdio")