# Merge Conflict Resolver

An MCP server (plus a REST API) that lets an AI assistant read your Git merge conflicts and propose a resolution for each one, without ever touching your files. Built for developers who want help with conflicts from inside Claude Code, Claude Desktop, GitHub Copilot CLI, or any other MCP-compatible host.

## How it works

- **Parser:** reads conflicted files in a local Git repo and splits them into hunks (`ours`, `theirs`, surrounding context, branch name).
- **Shared service layer:** the parsing and resolution logic lives in `app/services/`, so the REST API and the MCP server both call the same functions.
- **MCP layer (`mcp_server.py`):** the host launches it as a local process over stdio. It exposes four tools. For `smart` resolutions it returns the raw hunk and the host's own model writes the merge. No second LLM is involved.
- **REST layer (FastAPI):** for callers with no host model (e.g. a future CI job). Here `smart` calls Gemini.

```
REST client ──────> FastAPI routes ──┐
                                      ├──> services/ (git_parser.py, resolver.py)
MCP host ─────────> mcp_server.py ───┘
(Claude Code, Claude Desktop, Copilot CLI, ...)
```

**Propose-only by design.** The server never writes to your files, stages, or commits. See [Design decisions](#design-decisions).

## Tools exposed

| Tool | What it does | Parameters |
|---|---|---|
| `analyze_conflicts` | Scans a repo and returns conflicted files with their hunks, plus per-file `warnings` and a top-level `message`. Call this first. | `repo_path` (string, absolute path) |
| `resolve_conflict` | Proposes a resolution for one hunk. | `hunk_id` (string, from `analyze_conflicts`), `strategy` (`ours` \| `theirs` \| `smart`) |
| `list_resolution_history` | Lists the `ours`/`theirs` resolutions proposed this session. | none |
| `clear_resolution_history` | Clears this session's history and returns how many entries were removed. | none |

### Strategies

| Strategy | Behavior |
|---|---|
| `ours` | Keep the current branch (HEAD) side. Returns a filled resolution. |
| `theirs` | Take the incoming side. Returns a filled resolution. |
| `smart` | **MCP:** returns only the raw hunk; the host model reasons about it and produces the resolution. No Gemini key needed. **REST:** calls Gemini. |

### Resolution shape

```json
{
  "resolution": "string",
  "reasoning": "string",
  "confidence": "high | medium | low",
  "risk_flag": "low | medium | high",
  "strategy": "took_ours | took_theirs | merged_both | rewrote"
}
```

`risk_flag` is a hardcoded `"low"` placeholder on `ours`/`theirs` until real risk logic exists. Treat it as "not assessed", not "safe".

---

# Part 1: Set up the MCP server

## 1.1 Prerequisites

- Python 3 (developed and tested on Python 3.14, Windows)
- Git
- At least one MCP host: [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli), Claude Code, and/or Claude Desktop

## 1.2 Install

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

python -m venv venv

# Windows (Command Prompt)
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

**No API key is needed for the MCP server**, for any of the three strategies. A Gemini key is only used by the REST API's `smart` strategy (see [Part 4](#part-4-rest-api)).

## 1.3 Collect two absolute paths

Both hosts need these, and relative paths will fail because hosts launch the server from their own working directory:

1. **The venv's Python executable**
   - Windows: `C:\path\to\your-repo\venv\Scripts\python.exe`
   - macOS / Linux: `/path/to/your-repo/venv/bin/python`
2. **`mcp_server.py`**
   - Windows: `C:\path\to\your-repo\mcp_server.py`
   - macOS / Linux: `/path/to/your-repo/mcp_server.py`

Use the **venv's** Python, not just `python`. If the host launches a different interpreter, it won't have the dependencies and the server will fail with `ModuleNotFoundError`.

## 1.4 Make a test repo with a real conflict

The merge stops with a conflict. `git status` should show **Unmerged paths**. Leave the repo in this state for testing.

## 1.5 Connect your host

Pick the host you use and click to expand its instructions.

<details>
<summary><b>GitHub Copilot CLI</b></summary>

**Option A: interactive form**

1. Start Copilot with `copilot` and run `/mcp add`. Use Tab to move between fields.
2. Fill in:
   - **Server name:** `merge-conflict-resolver`
   - **Server type:** Local / STDIO
   - **Command:** the Python path and script path on one line, each in double quotes (paths with spaces need this):
     ```
     "C:\path\to\your-repo\venv\Scripts\python.exe" "C:\path\to\your-repo\mcp_server.py"
     ```
   - **Environment variables:** leave empty
   - **Tools:** `*`
   - **Defer tools:** `2. Never` (only four tools, so always load them)
3. Press **Ctrl+S** to save. It is available immediately; no restart needed.

**Option B: edit the config file** at `~/.copilot/mcp-config.json` (on Windows, `C:\Users\<you>\.copilot\mcp-config.json`). Arguments are a proper list here, so spaces in paths are safe:

```json
{
  "mcpServers": {
    "merge-conflict-resolver": {
      "type": "local",
      "command": "C:\\path\\to\\your-repo\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\your-repo\\mcp_server.py"],
      "tools": ["*"]
    }
  }
}
```

(Backslashes are doubled because this is JSON.)

**Verify:** in a Copilot session, run `/mcp`. The server should be listed as connected with four tools.

</details>

<details>
<summary><b>Claude Code</b></summary>

Claude Code registers MCP servers with the `claude mcp add` command.

1. Run this from any folder, using your own absolute paths:

   ```bash
   claude mcp add --transport stdio --scope user merge-conflict-resolver -- "C:\path\to\your-repo\venv\Scripts\python.exe" "C:\path\to\your-repo\mcp_server.py"
   ```

   macOS / Linux:

   ```bash
   claude mcp add --transport stdio --scope user merge-conflict-resolver -- /path/to/your-repo/venv/bin/python /path/to/your-repo/mcp_server.py
   ```

   - **`--scope user`** makes the server available in every repo you open Claude Code in. The default scope (`local`) only applies to the folder where you ran the command, which is the wrong fit for a tool you will use across many repos.
   - Everything after the `--` is the command that launches the server. Options like `--transport` and `--scope` must come before the server name.
   - Quote both paths if they contain spaces.
2. **Verify:** run `claude mcp list` to confirm the server is registered. Inside a Claude Code session, `/mcp` shows its status and tools.
3. If a session was already open, restart it.

Claude Code asks for approval the first time it uses a tool.

> **Project scope:** `--scope project` writes a `.mcp.json` into the repo, intended to be committed and shared. It is a poor fit here because the command contains machine-specific absolute paths.

</details>

<details>
<summary><b>Claude Desktop</b></summary>

1. Open Claude Desktop, then **Settings > Developer > Edit Config**. This opens `claude_desktop_config.json`.
   - Windows default: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS default: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Add the server under `mcpServers`:

   ```json
   {
     "mcpServers": {
       "merge-conflict-resolver": {
         "command": "C:\\path\\to\\your-repo\\venv\\Scripts\\python.exe",
         "args": [
           "C:\\path\\to\\your-repo\\mcp_server.py"
         ]
       }
     }
   }
   ```

3. **Fully quit Claude Desktop** (from the system tray, not just the window) and reopen it.
4. **Verify:** Settings > Developer should show `merge-conflict-resolver` as running.

</details>

> Restart the host any time you change `mcp_server.py`. Tool descriptions are read when the server starts.

---

# Part 2: Add the skill file (optional but recommended)

The skill file is a short set of instructions that teaches the host model *how* to use the tools: when to activate, the analyze → resolve one hunk at a time → summarize workflow, how to reason through a `smart` hunk, and the safety rules.

It is **optional**. The most important rules (the server is local and not sandboxed, how `smart` works, propose-only) are also written into the tool descriptions, so they reach any host. The skill adds the full workflow and activates the tools when you just say "I have merge conflicts."

The skill lives in this repo at:

```
.github/skills/merge-conflict-resolver/SKILL.md
```

The folder name must match the `name` in the file's frontmatter, and must use hyphens, not spaces.

## 2.1 Install the skill

Pick your host and click to expand.

<details>
<summary><b>GitHub Copilot CLI</b></summary>

Copilot loads project skills from `.github/skills/` only when it is opened *inside that repo*. You will usually run it in other repos, so install the skill for your user account:

1. Copy the whole `merge-conflict-resolver` folder (containing `SKILL.md`) into your personal skills folder:
   - Windows: `C:\Users\<you>\.copilot\skills\merge-conflict-resolver\SKILL.md`
   - macOS / Linux: `~/.copilot/skills/merge-conflict-resolver/SKILL.md`
2. In Copilot, run `/skills reload` (or restart it).
3. **Verify:** `/skills list` should show `merge-conflict-resolver`. `/skills info` shows where it was loaded from.

If you open Copilot inside this repo, you may see the skill listed twice (project copy and personal copy). That is harmless.

</details>

<details>
<summary><b>Claude Code</b></summary>

Claude Code loads skills from `~/.claude/skills/` (personal, all repos) or `.claude/skills/` inside a repo. It does not read this repo's `.github/skills/` folder, so copy the skill:

1. Copy the whole `merge-conflict-resolver` folder (containing `SKILL.md`) into your personal skills folder:
   - Windows: `C:\Users\<you>\.claude\skills\merge-conflict-resolver\SKILL.md`
   - macOS / Linux: `~/.claude/skills/merge-conflict-resolver/SKILL.md`
2. Start a **new** Claude Code session.
3. **Verify:** in a repo with conflicts, say "I have merge conflicts, help me resolve them" without naming any tools. The host should reach for the `merge-conflict-resolver` tools by itself.

> According to GitHub's docs, Copilot CLI also scans `~/.claude/skills/`, so a single copy there may serve both tools. Check with `/skills list` in Copilot.

</details>

<details>
<summary><b>Claude Desktop</b></summary>

Claude Desktop installs skills as a zip upload, not from a folder.

1. In **Settings > Capabilities**, enable **Code execution and file creation** (skills need it). Custom skills are only available on paid plans.
2. **Zip the skill folder** so the zip contains the `merge-conflict-resolver` folder at its top level, with `SKILL.md` inside it. (Right-click the folder > Send to > Compressed folder on Windows.)
3. Go to **Settings > Capabilities > Skills** (also reachable under **Customize > Skills**), click **Upload skill**, and choose the zip. A preview and a security scan run before upload.
4. Make sure the skill is toggled **on** in **Your skills**.
5. Start a **new chat**. Skills are loaded per conversation.

If the upload misbehaves, a fallback is to paste the body of `SKILL.md` into a Claude Project's custom instructions and use the tools from inside that project.

</details>

> **Note for contributors:** the `description` line in the skill's frontmatter must not contain angle brackets. Claude's upload validator rejects anything that looks like an XML tag, which includes raw conflict markers.

---

# Part 3: Using it

Open your host in (or point it at) a repo that is mid-merge, then just describe the problem in plain English. You don't call tools by name.

**Copilot CLI:** `cd` into the conflicted repo, run `copilot`, and say something like:

> I have merge conflicts in this repo. Use the merge-conflict-resolver tools, only propose resolutions, and don't edit any files.

**Claude Code:** `cd` into the conflicted repo, run `claude`, and say something like:

> I have merge conflicts in this repo. Use the merge-conflict-resolver tools, only propose resolutions, and don't edit any files.

**Claude Desktop:** in a new chat:

> I have merge conflicts in `C:\path\to\conflict-practice`, help me resolve them.

Approve the tool call when prompted. **Allow once** is a sensible default. **Always allow** would also skip the prompt for `clear_resolution_history`.

A good session looks like this:

1. The host calls `analyze_conflicts` and reports the files, hunk IDs, and any `warnings` or `message`.
2. It asks which strategy you want if you didn't say (`ours`, `theirs`, or a merged result via `smart`).
3. It resolves one hunk at a time. For `smart`, it fills in `resolution`, `reasoning`, `confidence`, and `risk_flag` itself.
4. It ends with a summary of each hunk and anything that needs your review.
5. It does **not** edit files, stage, or commit unless you explicitly approve.

Applying a proposed resolution is up to you (or your host's own edit tools, with your approval).

---

# Part 4: REST API

The same core logic is also available over HTTP, for callers with no host model.

**Live deployment (Render free tier):** https://merge-conflict-resolver.onrender.com

The free tier spins down when idle, so the first request after a quiet period can take a while. In-memory state (analyzed hunks, history) is also lost on restart, so call `/analyze` again before `/resolve` if the server has been asleep. Interactive docs are at `/docs`.

### Run it locally

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/).
2. Create a `.env` file in the repo root (it is gitignored; never commit it):
   ```
   GEMINI_API_KEY=your-key-here
   ```
3. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```
4. Open `http://127.0.0.1:8000/docs`.

The free tier is limited (about 5 requests per minute and 20 per day during development), so a `503` with retry guidance is expected if you hit it.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/analyze` | Scan a repo (`repo_path`) and return conflicted files with hunks |
| `POST` | `/resolve` | Propose a resolution for a `hunk_id` with a `strategy`. `smart` calls Gemini. |
| `GET` | `/history` | This session's proposed resolutions |
| `DELETE` | `/history` | Clear this session's history |

Sessions are scoped by the `X-Session-Id` header. If it is missing, the server generates one and returns it in the response header.

Errors: `400` (bad repo path, or no `.git`), `404` (unknown `hunk_id`), `422` (invalid strategy), `503` (Gemini unavailable, with `Retry-After`), `500` (unexpected). See `docs/api spec.md` for the full contract.

---

## Design decisions

- **`smart` differs by interface, same schema.** REST has no host model, so it calls Gemini. MCP always has one, so a second LLM inside a tool would add latency and a needless API dependency. MCP `smart` returns the raw hunk and the host reasons about it.
- **Propose-only, no `apply_resolution` tool.** Hosts that can edit files already have their own edit tools with their own approval prompts. Writing back from this server would be risky today: `hunk_id` is `filepath::index` and can go stale or shift after a file changes, resolving one hunk moves the line numbers of later ones, and `\r\n` line endings are normalized on read, so a write-back could silently change a file's line endings. If it is added later, it should re-verify the conflict block before writing, apply hunks bottom-up, preserve line endings, and never stage or commit.
- **One fixed session per MCP process.** MCP over stdio has no HTTP headers, so the server generates a single session ID at startup. History resets when the host restarts the server.
- **Large hunks (REST `smart` only).** Each side is capped at 200 lines (first and last 100 kept) when building the Gemini prompt, and the result is forced to `confidence: "low"` with a warning. The cap does not apply on MCP.
- **Malformed input never crashes analysis.** Broken or unfinished conflict markers, binary files, and unreadable files become per-file `warnings` instead of errors.

## Known limitations

- Conflict markers at column 0 inside string literals (for example, test fixtures) can't be told apart from real ones by a line-based parser and may produce a spurious hunk.
- diff3 / zdiff3 style conflicts (with a `|||||||` base section) are not supported; base text is read as part of `ours`.
- Only the default 7-character marker length is supported.
- `hunk_id` doesn't encode the repo, so two repos with the same relative file path can collide. Re-run `analyze_conflicts` after any file changes.
- State is in memory only and resets when the server restarts.
- On MCP, `smart` resolutions are produced by the host and never recorded in `list_resolution_history`.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'dotenv'` (or another package) | The host launched a different Python. Point the command at the venv's Python and re-run `pip install -r requirements.txt` inside that venv. |
| "Server transport closed unexpectedly" | The script isn't starting the server. Make sure `mcp_server.py` ends with `mcp.run(transport="stdio")` under `if __name__ == "__main__":`. |
| Server fails to start in Copilot | Quote both paths if they contain spaces, or use the `mcp-config.json` method where arguments are a list. |
| Host says it can't access your files, or claims a sandbox | The server runs locally with real filesystem access. Tell the host to just try the tool call. Installing the skill file reduces this. |
| Tool descriptions look old after an edit | Fully restart the host so it restarts the MCP server. |
| Claude Code: server works in one folder but not in other repos | It was added with the default `local` scope. Remove it (`claude mcp remove merge-conflict-resolver`) and re-add it with `--scope user`. |
| `/mcp` is missing or blocked in Copilot | MCP can be disabled by default in GitHub organizations. An admin has to enable it. |
| `analyze_conflicts` finds nothing | Run `git status` and check for **Unmerged paths**. A merge that was already resolved or aborted has no conflicts. Also check `warnings` and `message` in the output. |
| `hunk_id` not found | Re-run `analyze_conflicts` and use the new IDs. IDs go stale after files change. |
| Files in OneDrive fail to upload or read oddly | Wait for OneDrive to finish syncing, or work from a non-synced folder. |

## Project structure

```
app/
  models/schemas.py        Pydantic models and enums
  routes/                  Thin FastAPI routes (analyze, resolve, history)
  services/
    git_parser.py          Conflict detection and parsing
    resolver.py            Resolution logic, Gemini call, history
  state.py                 In-memory stores
  main.py                  FastAPI app
docs/
  api spec.md              API design doc
.github/skills/
  merge-conflict-resolver/
    SKILL.md               Skill file for MCP hosts
mcp_server.py              MCP server (stdio)
requirements.txt
```

## Tech stack

Python, FastAPI, Pydantic, MCP Python SDK (v2, `MCPServer`), Google Gemini API (`google-genai`, `gemini-3.6-flash`, free tier), `python-dotenv`. Deployed on Render.