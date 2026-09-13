# Merge Conflict Resolver — API Spec (Revised)

Design doc for all endpoints, written before implementation (Days 11–12).

---

## POST /analyze

**Purpose:** Scan a repo (or a diff payload) for merge conflicts, return structured hunks.

**Request:**
```json
{
  "repo_path": "string"
}
```
- **Deferred:** a `diff_payload` alternative (for a future CI/GitHub Action integration, Day 27
  candidate, where there's no local clone to point a path at) was considered but pushed to after
  the core project works end-to-end. Revisit this endpoint's schema then — it may need a
  non-breaking addition at that point.

**Success (200):**
```json
{
  "repo_path": "string",
  "conflicted_files": [
    {
      "filepath": "string",
      "conflict_count": 0,
      "hunks": [
        {
          "hunk_id": "string",
          "ours": "string",
          "theirs": "string",
          "branch_name": "string",
          "context_before": "string",
          "context_after": "string",
          "line_number": 0
        }
      ]
    }
  ],
  "total_conflicts": 0
}
```

**Errors:**
- `400` — `repo_path` does not exist on disk
- `400` — `repo_path` exists but has no `.git` folder
- `200` — no conflicts found → empty `conflicted_files` list, `total_conflicts: 0` (this is NOT an error case)
- `500` — underlying git command failed for another reason

---

## POST /resolve

**Purpose:** Propose a resolution for one conflict hunk.

**Request:**
```json
{
  "hunk": {
    "hunk_id": "string",
    "ours": "string",
    "theirs": "string",
    "branch_name": "string",
    "context_before": "string",
    "context_after": "string"
  },
  "strategy": "smart",
  "repo_path": null
}
```
**Required header:** `X-Session-Id: string` (optional on first request — see below)

- `strategy` is an Enum: `"ours" | "theirs" | "smart"`, defaults to `"smart"`.
- `repo_path` is **optional**, defaults to `null`. Not used yet — reserved for the Day 27 optional
  improvement (passing `git log --oneline` context to the LLM). Added now as optional so the request
  schema doesn't need a breaking change later.
- Design decision: `hunk` is fully self-contained (carries ours/theirs/context) for the current
  "smart" resolution logic. `repo_path` is the only field that would require filesystem access, and
  it's unused for now.
- **Session handling:** if `X-Session-Id` is present, use it. If absent, the server generates a new
  UUID, creates an empty history bucket for it, and returns it via an `X-Session-Id` response header.
  Server-generated over client-chosen because a client could pick a colliding/guessable ID and see
  another user's history — the server is the only party that can guarantee uniqueness.

**Success (200):**
```json
{
  "resolution": "string",
  "reasoning": "string",
  "confidence": "high",
  "risk_flag": "low",
  "strategy": "took_ours"
}
```
- `confidence` is one of `"high" | "medium" | "low"` — how sure the LLM is about the suggestion.
- `risk_flag` is one of `"low" | "medium" | "high"` — how dangerous it is if the suggestion is wrong,
  independent of confidence (e.g. a confident suggestion touching `auth.py` can still be high-risk).
  Placeholder for now: return `"low"` for every response until real flagging logic
  (file-path rules, keyword checks, etc.) is built. Included now so the response schema doesn't
  change shape later.
- `strategy` (in the response) is one of `"took_ours" | "took_theirs" | "merged_both" | "rewrote"`.

**Errors:**
- `422` — invalid `strategy` value in request (Pydantic/Enum catches this automatically)
- `503` — Gemini API call failed (rate limit / network error) — response should include retry guidance
- `500` — unexpected failure (e.g. malformed hunk data)

---

## GET /history

**Purpose:** Return all resolutions proposed this session, scoped to the requesting session/user.

**Request:** none
**Required header:** `X-Session-Id: string`

If `X-Session-Id` is missing, treat it as a brand-new session: return an empty history and issue a
fresh `X-Session-Id` via response header (same behavior as `/resolve` — see there for rationale).

**Success (200):**
```json
{
  "history": [
    {
      "hunk_id": "string",
      "result": {
        "resolution": "string",
        "reasoning": "string",
        "risk_flag": "string",
        "strategy": "string"
      }
    }
  ],
  "count": 0
}
```
Only entries belonging to the given `X-Session-Id` are returned — never another session's history.

**Errors:** none expected. Empty history for a valid (or newly-generated) session returns `200` with
an empty list — not an error.

**Design decisions:**
- History is stored in-memory as `dict[session_id, list]`, keyed by `X-Session-Id`. This fixes
  cross-user leakage (two people no longer see each other's resolutions).
- Data is still lost on server restart (e.g. Render free-tier spin-down). This is an accepted
  limitation for a learning project, not a bug — documented here so it's not a surprise later.
  Scoping by session solves *whose* history it is, not *how long* it survives.

---

## DELETE /history

**Purpose:** Clear history for the requesting session/user only.

**Request:** none
**Required header:** `X-Session-Id: string`

If `X-Session-Id` is missing, there's nothing to delete for a session that doesn't exist yet — the
server generates a fresh one (empty by definition) and returns `deleted_count: 0`.

**Success (200):**
```json
{
  "deleted_count": 0
}
```
`deleted_count` reflects only entries removed from this session's history — other sessions are untouched.

**Errors:** none expected. Clearing an already-empty or nonexistent session still returns `200` with
`deleted_count: 0` — not an error.

---

## Open questions / assumptions to revisit

- [x] ~~Should `/resolve` accept a `repo_path` as well, in case future strategies need filesystem context?~~
      Resolved: added as optional field, defaults to `null`, unused until Day 27.
- [x] ~~Should history be keyed by session/user, or is a single global in-memory list acceptable for now?~~
      Resolved: keyed by `X-Session-Id` header across `/resolve`, `GET /history`, `DELETE /history`.
- [x] ~~Who generates `X-Session-Id` — client or server?~~
      Resolved: server auto-generates on first contact (when header is absent) and returns it via a
      response header. Client-supplied IDs are trusted if already present. Server-generated avoids
      collision/guessing risk since the server is the only party that can guarantee uniqueness.
- [x] ~~Should `/resolve` responses carry a risk signal separate from confidence?~~
      Resolved: added `risk_flag` (`low`/`medium`/`high`), placeholder `"low"` until real logic exists.
- [ ] Should `/analyze` support something other than a local repo path (e.g. `diff_payload`)?
      Deferred — revisit after the core project is functional end-to-end. Likely needed for the
      Day 27 CI/GitHub Action candidate, since a CI runner won't have a persistent local clone.
- [ ] What's the max hunk size passed to Gemini before truncating context (see Day 24 edge case: >200 line hunks)?