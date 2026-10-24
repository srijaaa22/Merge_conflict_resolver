---
name: merge-conflict-resolver
description: Use when the user mentions merge conflicts, a failed merge or rebase, git conflict markers, or unmerged paths. Analyzes a local git repo's conflicts and proposes a resolution for each hunk using the merge-conflict-resolver MCP tools. Proposes only; never applies changes.
---

# Merge Conflict Resolver

## This server runs locally

The merge-conflict-resolver MCP server runs as a local process on the user's own machine. It calls `git` and reads files directly, with full access to the user's real filesystem. It is not sandboxed and not remote.

Do not assume you lack access to the user's files. Attempt the tool call first. Only report a problem if the call actually fails.

## Tools

- `analyze_conflicts(repo_path)`: scans the repo and returns conflicted files with their hunks. Each hunk has a `hunk_id`, `ours`, `theirs`, `branch_name`, `context_before`, `context_after`, and `line_number`.
- `resolve_conflict(hunk_id, strategy)`: `strategy` is `ours`, `theirs`, or `smart`.
- `list_resolution_history()`: past `ours`/`theirs` resolutions from this session.
- `clear_resolution_history()`: empties that history.

## Workflow

1. Run `analyze_conflicts` on the repo path first. Hunk IDs only exist after this call.
2. Report what came back: files, hunk counts, and anything in `warnings` or `message`. Always surface these to the user. They explain skipped files (binary, unreadable, deleted), malformed or unfinished conflicts, and files with no markers that may already be resolved.
3. Resolve one hunk at a time, not all at once.
4. Finish with a short summary: each hunk, the strategy used, the proposed result, and anything the user needs to decide or review.

## Choosing a strategy

- If the user names a side ("keep mine", "take theirs"), use `ours` or `theirs`.
- If the user wants a combined or rewritten result, use `smart`.
- If the user doesn't specify, show both sides briefly and ask which they want. Do not pick `smart` silently.

## How `smart` works (important)

For `smart`, the server does not resolve anything. It returns only the raw hunk. You produce the resolution yourself.

Reason from the returned data:
- Read `ours` and `theirs` in full, and what each side is trying to do.
- Use `context_before` and `context_after` to understand surrounding code.
- Use `branch_name` to see where each side came from.
- Keep the intent of both sides where they are compatible. If they truly conflict, say so and choose one with a reason.
- Never invent code that isn't in either side or the context. If something looks missing, say so.

Present the result in this shape:
- `resolution`: the final text for the hunk
- `reasoning`: why, in a few sentences
- `confidence`: `high`, `medium`, or `low`
- `risk_flag`: `low`, `medium`, or `high`
- `strategy`: `merged_both` or `rewrote`

Your `smart` resolutions are not recorded by the server, so they will not appear in history.

## Reading tool output

- `confidence`: how sure the resolution is.
- `risk_flag`: how bad it is if the resolution is wrong, independent of confidence. For `ours` and `theirs`, the server returns `low` as a placeholder because real risk logic isn't built yet. Treat it as "not assessed," not as "safe." Judge risk yourself: raise it for hunks touching auth, security, permissions, config, secrets, database migrations, or code that deletes data.
- `strategy`: `took_ours`, `took_theirs`, `merged_both`, or `rewrote`.

## Safety rules

- This server only proposes resolutions. It never writes to files.
- Do not apply a resolution to any file unless the user explicitly approves it. This includes using your own file-editing tools.
- Do not stage, commit, or continue or abort the merge or rebase on your own.
- Surface any resolution with `risk_flag` of `medium` or `high`, or `confidence` of `low`, to the user. Never apply it quietly.

## Errors and stale data

- If `resolve_conflict` reports the hunk was not found, re-run `analyze_conflicts` and use the new IDs. IDs are based on file path and position, so they can shift after a file changes. Always re-analyze after the user edits a conflicted file.
- If analysis finds no conflicts, say so plainly. Check `message` and `warnings` before concluding anything.
- The parser assumes standard git conflict markers. It does not support the diff3 style (`|||||||` base section), so base text may appear inside `ours`. Mention this if a hunk looks odd.