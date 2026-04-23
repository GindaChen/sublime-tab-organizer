# sublime-tab-organizer

Organize Sublime Text tabs from your shell. List, merge, sort, dedupe, close, and persist untitled buffers — all without leaving the terminal.

```
$ sto list
* window 3  (12 tabs)
      14521  /Users/you/Projects/foo/src/main.py
    ● 14522  /Users/you/Projects/foo/tests/test_main.py
      14523  [untitled]
  window 5  (4 tabs)
      14600  /Users/you/scratch/notes.md
```

`●` = unsaved.

## Why

Sublime has no built-in command for "merge all my windows" or "save every untitled tab to a folder." This fills in those gaps with a small CLI (`sto`) that drives a companion plugin running inside ST.

## Architecture

ST's plugin API only runs inside the ST process, so a plain CLI can't call it directly. This repo ships two halves:

```
  your shell                      Sublime Text
  ┌──────────┐   TCP 9998    ┌──────────────────────┐
  │   sto    │ ────────────→ │  SublimeTabOrganizer │
  │   CLI    │ ←──────────── │   (plugin, python)   │
  └──────────┘    JSON/L     └──────────────────────┘
```

- `plugin/SublimeTabOrganizer.py` — runs inside ST, listens on `127.0.0.1:9998`, dispatches commands on ST's main thread.
- `cli/sto` — Python 3 CLI that sends one JSON request per invocation.

## Install

```bash
git clone https://github.com/GindaChen/sublime-tab-organizer.git
cd sublime-tab-organizer
./install.sh
```

`install.sh` copies the plugin into `~/Library/Application Support/Sublime Text/Packages/User/` and the CLI into `~/.local/bin/sto`. **Restart Sublime Text once** so the plugin loads.

Verify:

```bash
sto ping
# {"pong": true, "version": "0.1.0", "windows": 2}
```

## Commands

Run `sto --help` for the full menu and `sto <cmd> --help` for per-command examples.

### `sto list`

Every window and tab with view IDs (use these with `sto close`). `*` marks the active window; `●` marks unsaved buffers.

### `sto merge [--into N] [--copy-unsaved]`

Pulls saved tabs from every other window into the target window (active by default), then closes the empty source windows.

- Saved, clean tabs are re-opened by path — lossless.
- Dirty / untitled tabs are skipped unless `--copy-unsaved`.
- With `--copy-unsaved`, the plugin re-materializes the buffer in a new view: text and syntax survive; undo history and view-local state (folds, bookmarks) do not. File association is lost for dirty-with-path buffers.
- ST has no cross-window move API (confirmed against the official API reference); re-opening by path or copying contents is the only option.

### `sto dump-untitled [--dir PATH] [--close-source] [--open-saved] [--include-dirty]`

Persist untitled buffers to disk as real files.

**Filename scheme:** `YYYYMMDD_HHMMSS_<slug>.<ext>`

- timestamp = the dump invocation time
- slug = first non-blank line, stripped of comment markers (`#`, `//`, `--`), kebab-cased, capped at 40 chars
- ext = inferred from the view's syntax (`.py`, `.md`, `.sh`, `.json`, ... fallback `.txt`)

**Content dedup:** before writing, every file in the destination is sha256-hashed. If a buffer's hash matches an existing file, the write is skipped and that path is reused. Running this repeatedly does not pile up identical files.

```bash
sto dump-untitled                              # → ~/sublime-scratch/
sto dump-untitled --dir ~/notes/scratch
sto dump-untitled --close-source --open-saved  # save, close untitled, reopen as file-backed
```

### `sto close [IDS ...] [--pattern GLOB] [--saved]`

Close tabs by view id, by fnmatch glob against the file path, or every clean tab.

```bash
sto close 14521 14522
sto close --pattern '*/node_modules/*'
sto close --saved          # keeps dirty tabs
```

### `sto sort [--by name|path|ext]`

Re-order tabs within the active window's active group. Group-scoped because the ST API is group-scoped.

### `sto dedupe`

If the same file path is open in multiple tabs, keeps the first seen and closes the rest.

### `sto group-by-folder`

Splits tabs across new windows by project folder. Keeps tabs under the first folder in the active window; moves tabs under each other folder into their own new window.

### `sto ping`

Health check. Prints plugin version + window count. Exit 2 if the plugin is unreachable.

## Environment

| var | default | used by |
|---|---|---|
| `STO_HOST` | `127.0.0.1` | CLI connects here |
| `STO_PORT` | `9998` | CLI connects here |
| `STO_SCRATCH_DIR` | `~/sublime-scratch` | `dump-untitled` default `--dir` |

## Caveats

- **macOS paths assumed** in `install.sh` (`~/Library/Application Support/Sublime Text/Packages/User/`). Linux/Windows paths differ — override with `STO_PLUGIN_DIR`.
- **Dirty-tab close prompts.** `sto close` on a dirty tab shows ST's "save changes?" dialog — the CLI will appear to hang until you answer. Use `--saved` to avoid prompts.
- **One TCP port.** If something else is on `9998`, set `STO_PORT` and edit the constant in `plugin/SublimeTabOrganizer.py` to match.
- **No auth on the TCP server.** It binds to `127.0.0.1` only, but any local process can talk to it. Fine for personal use; don't run on shared machines.

## Roadmap

- Sublime Text command-palette entries that call the same handlers (`sto` without a shell).
- Session save/restore to JSON (named layouts you can reload weeks later).
- Windows / Linux `install.sh` paths.
- `--dry-run` on every destructive command.

## License

MIT. See `LICENSE`.
