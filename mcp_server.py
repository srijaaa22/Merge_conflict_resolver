import uuid

from mcp.server import MCPServer
from app.services.git_parser import analyze_repo
from app.services.resolver import resolve_hunk, get_hunk, get_history, clear_history
from app.models.schemas import Strategy, HistoryEntry

mcp = MCPServer("merge-conflict-resolver")

SESSION_ID = str(uuid.uuid4())

@mcp.tool()
def analyze_conflicts(repo_path : str) -> dict:
    """
    Scan a Git repository for merge conflicts.
    Returns all conflicted files and their parsed hunks
    with surrounding context. Use this first to understand
    what conflicts exist before attempting resolution.
    """
    return analyze_repo(repo_path)

@mcp.tool()
def resolve_conflict(hunk_id: str, strategy: Strategy = Strategy.SMART) -> dict:
    """
    Propose a resolution for a single conflict hunk.
    strategy: 'ours' (keep HEAD version), 'theirs' (take incoming),
    'smart' returns the raw hunk (ours/theirs/context/branch) — 
    no LLM is called here. 
    You must reason about the conflict yourself and 
    produce the resolution, reasoning, confidence, and risk_flag.
    """
    if strategy == Strategy.OURS or strategy == Strategy.THEIRS:
        return resolve_hunk(hunk_id, strategy, SESSION_ID).model_dump()
    else:
        return get_hunk(hunk_id)
    
@mcp.tool()
def list_resolution_history() -> list[HistoryEntry]:
    """
    Return all deterministic (ours/theirs) conflict resolutions proposed
    so far in this server session. Each entry includes the hunk_id and
    the resolution result (resolution, reasoning, confidence, risk_flag,
    strategy). Note: 'smart' resolutions are reasoned by the host model
    directly and are not recorded here. Use this to review what's been
    resolved so far, or if the user asks.
    """
    return [entry.model_dump() for entry in get_history(SESSION_ID)]

@mcp.tool()
def clear_resolution_history() -> int:
    """
    Clear all resolution history for this server session. Returns the
    number of entries removed. Only call this if the user explicitly
    asks to clear or reset history — do not call this on your own
    initiative.
    """
    return clear_history(SESSION_ID)

if __name__ == "__main__":
    mcp.run(transport="stdio")