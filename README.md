# sublime-tab-organizer

> Organize Sublime Text tabs from your shell — `list` · `merge` · `sort` · `dedupe` · `dump-untitled`.

[![license](https://img.shields.io/badge/license-MIT-3b82f6)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.8%2B-3776ab?logo=python&logoColor=white)](#)
[![sublime](https://img.shields.io/badge/sublime_text-4-ff9800?logo=sublimetext&logoColor=white)](https://www.sublimetext.com/)
[![platform](https://img.shields.io/badge/platform-macOS-a3a3a3)](#)
[![version](https://img.shields.io/badge/version-0.1.0-6fbf8a)](#)
[![landing](https://img.shields.io/badge/site-gindachen.github.io-6c8bef)](https://gindachen.github.io/sublime-tab-organizer/)

---

## install

```bash
git clone https://github.com/GindaChen/sublime-tab-organizer.git
cd sublime-tab-organizer && ./install.sh
# restart Sublime Text once, then:
sto ping
```

## commands

| cmd                     | does                                        | example                            |
| ----------------------- | ------------------------------------------- | ---------------------------------- |
| `sto list`              | show windows + tabs (view IDs, `●` = dirty) | `sto list --json \| jq .`          |
| `sto merge`             | pull every window's saved tabs into one     | `sto merge --copy-unsaved`         |
| `sto sort`              | sort active group (name / path / ext)       | `sto sort --by path`               |
| `sto dedupe`            | close duplicate file tabs                   | `sto dedupe`                       |
| `sto close`             | close by id, glob, or saved state           | `sto close --pattern '*.log'`      |
| `sto dump-untitled`     | save untitled buffers to disk               | `sto dump-untitled --close-source` |
| `sto group-by-folder`   | split tabs by project folder                | `sto group-by-folder`              |
| `sto ping`              | plugin health check                         | `sto ping`                         |

Per-command examples: `sto <cmd> --help`.

## demo

```text
$ sto list
* window 3  (8 tabs)
      14521  /Users/you/proj/src/main.py
    ● 14522  /Users/you/proj/tests/test_main.py
      14523  [untitled]
  window 5  (4 tabs)
      14600  /Users/you/notes/meeting.md

$ sto dump-untitled --close-source --open-saved
saved   /Users/you/sublime-scratch/20260423_091204_untitled.txt
saved   /Users/you/sublime-scratch/20260423_091204_todo-refactor.md
2 new, 0 reused (content-dedup)

$ sto merge
merged 4 tabs into window 3
```

## dump-untitled: filename scheme

`YYYYMMDD_HHMMSS_<slug>.<ext>`

- **timestamp** — dump invocation time (one per run, keeps a batch visually grouped).
- **slug** — first non-blank line, comment markers stripped, kebab-cased, 40-char cap.
- **ext** — inferred from `view.syntax()` (`.py`, `.md`, `.sh`, `.json`, ...); fallback `.txt`.
- **dedup** — sha256 of contents; identical buffers reuse the existing file.

Default dir: `~/sublime-scratch` (override with `--dir` or `$STO_SCRATCH_DIR`).

## architecture

```text
  your shell                      Sublime Text
  ┌──────────┐   TCP 9998    ┌──────────────────────┐
  │   sto    │ ────────────→ │  SublimeTabOrganizer │
  │   CLI    │ ←──────────── │   (plugin, python)   │
  └──────────┘   JSON line   └──────────────────────┘
```

ST's plugin API only runs inside ST, so the CLI talks to a companion plugin over a local TCP socket. The plugin dispatches each command on ST's main thread.

**No cross-window move API exists** in ST (confirmed against the official API reference — `set_view_index` / `set_sheet_index` / `move_sheets_to_group` are all group-scoped). `merge` re-opens files by path for saved tabs; `--copy-unsaved` re-materializes the buffer in a new view (text + syntax survive; undo history and view-local state do not).

## env

| var                 | default             | used by                       |
| ------------------- | ------------------- | ----------------------------- |
| `STO_HOST`          | `127.0.0.1`         | CLI → plugin                  |
| `STO_PORT`          | `9998`              | CLI → plugin                  |
| `STO_SCRATCH_DIR`   | `~/sublime-scratch` | `dump-untitled` default `--dir` |
| `STO_PLUGIN_DIR`    | macOS Packages/User | `install.sh` destination      |
| `STO_CLI_DIR`       | `~/.local/bin`      | `install.sh` destination      |

## caveats

- macOS paths baked into `install.sh` — override with `STO_PLUGIN_DIR` on Linux/Windows.
- `sto close` on a dirty tab triggers ST's "save?" dialog; CLI hangs until you answer. Use `--saved` to skip.
- Plugin binds to `127.0.0.1` only, no auth. Fine for personal use; avoid on shared machines.
- `--copy-unsaved` preserves text + syntax; drops undo history and view-local state (folds, bookmarks).

## roadmap

- Command-palette entries inside ST (call the same handlers without a shell).
- Session save/restore (named layouts you can reload weeks later).
- Linux/Windows install paths.
- `--dry-run` on destructive commands.

## license

[MIT](./LICENSE) · [landing page](https://gindachen.github.io/sublime-tab-organizer/) · [source](https://github.com/GindaChen/sublime-tab-organizer)
