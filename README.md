# sublime-tab-organizer

> Stop dragging tabs between Sublime Text windows. Clean your Sublime using cli.

[![license](https://img.shields.io/badge/license-MIT-3b82f6)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.8%2B-3776ab?logo=python&logoColor=white)](#)
[![sublime](https://img.shields.io/badge/sublime_text-4-ff9800?logo=sublimetext&logoColor=white)](https://www.sublimetext.com/)
[![platform](https://img.shields.io/badge/platform-macOS-a3a3a3)](#)
[![version](https://img.shields.io/badge/version-0.2.0-6fbf8a)](#)
[![landing](https://img.shields.io/badge/site-gindachen.github.io-6c8bef)](https://gindachen.github.io/sublime-tab-organizer/)

---

## install

```bash
git clone https://github.com/GindaChen/sublime-tab-organizer.git
cd sublime-tab-organizer && ./install.sh
# restart Sublime Text once, then:
sto ping
```

`install.sh` also drops a Sublime command-palette file and shell completions (zsh/bash/fish).

## commands

### core

| cmd                     | does                                             | example                            |
| ----------------------- | ------------------------------------------------ | ---------------------------------- |
| `sto list`              | every window + tab, with view IDs (`●` = dirty)  | `sto list --json \| jq .`          |
| `sto close`             | close by id, glob, or saved state                | `sto close --pattern '*.log'`      |
| `sto merge`             | pull every window's tabs into one                | `sto merge --copy-unsaved`         |
| `sto move`              | move a single tab to another window              | `sto move 14522 --to 3`            |
| `sto sort`              | sort active group (name / path / ext)            | `sto sort --by path`               |
| `sto dedupe`            | close duplicate file tabs                        | `sto dedupe`                       |
| `sto dump-untitled`     | save untitled tabs to disk                       | `sto dump-untitled --close-source` |
| `sto group-by-folder`   | split tabs by project folder                     | `sto group-by-folder`              |

### search + bulk buffer ops

| cmd                     | does                                             | example                            |
| ----------------------- | ------------------------------------------------ | ---------------------------------- |
| `sto find`              | grep across every open buffer (including untitled) | `sto find 'TODO'`                |
| `sto save-all`          | save every dirty file-backed tab                 | `sto save-all`                     |
| `sto reload`            | revert tabs from disk (after `git checkout`)     | `sto reload --pattern '*/src/*'`   |

### sessions

| cmd                     | does                                             | example                            |
| ----------------------- | ------------------------------------------------ | ---------------------------------- |
| `sto save <name>`       | snapshot layout to `~/.sto/sessions/<name>.json` | `sto save work`                    |
| `sto restore <name>`    | reopen everything from a saved snapshot          | `sto restore work --close-existing`|
| `sto sessions`          | list / delete saved sessions                     | `sto sessions delete work`         |

### utility

| cmd                     | does                                             | example                            |
| ----------------------- | ------------------------------------------------ | ---------------------------------- |
| `sto recent`            | recently closed tabs (ring buffer, cap 100)      | `sto recent --restore 0`           |
| `sto pick`              | fuzzy-pick a tab via fzf, then act               | `sto pick close`                   |
| `sto ping`              | plugin health check                              | `sto ping`                         |

Every destructive command accepts `--dry-run`. Full per-command help: `sto <cmd> --help`.

## demo

```text
$ sto list
* window 3  (8 tabs)
      14521  /Users/you/proj/src/main.py
    ● 14522  /Users/you/proj/tests/test_main.py
      14523  [untitled]

$ sto save work
saved session: /Users/you/.sto/sessions/work.json
  2 windows, 12 views

$ sto find 'TODO' --regex
/Users/you/proj/src/main.py  view=14521  3 matches
  42:5  # TODO: refactor this path
  88:3  // TODO handle empty list
---
3 total matches in 1 views

$ sto merge --copy-unsaved --dry-run
merged 27 tabs into window 3 (dry-run)
  copied (untitled) [scratch]
```

## dump-untitled: filename scheme

`YYYYMMDD_HHMMSS_<slug>.<ext>`

- **timestamp** — dump invocation time (keeps a batch visually grouped).
- **slug** — first non-blank line, comment markers stripped, kebab-cased, 40-char cap.
- **ext** — inferred from `view.syntax()` (`.py`, `.md`, `.sh`, ...); fallback `.txt`.
- **dedup** — sha256 of contents; identical buffers reuse the existing file.

Default dir: `~/sublime-scratch` (override with `--dir` or `$STO_SCRATCH_DIR`).

## sublime command palette

After install, open ST's command palette (`cmd-shift-p`) and type `sto:` — entries for `merge`, `dedupe`, `sort`, `dump untitled`, `save all`, and `group by folder`. Same handlers as the CLI, no shell required.

## architecture

```text
  your shell                      Sublime Text
  ┌──────────┐   TCP 9998    ┌──────────────────────┐
  │   sto    │ ────────────→ │  SublimeTabOrganizer │
  │   CLI    │ ←──────────── │   (plugin, python)   │
  └──────────┘   JSON line   └──────────────────────┘
```

ST's plugin API only runs inside ST. The CLI talks to a companion plugin over a local TCP socket; the plugin dispatches each command on ST's main thread.

**No cross-window move API exists** in ST (confirmed against the official API reference). `merge` / `move` re-open files by path for saved tabs; `--copy-unsaved` re-materializes the buffer in a new view (text + syntax survive; undo history and view-local state do not).

## env

| var                 | default                      | used by                          |
| ------------------- | ---------------------------- | -------------------------------- |
| `STO_HOST`          | `127.0.0.1`                  | CLI → plugin                     |
| `STO_PORT`          | `9998`                       | CLI → plugin                     |
| `STO_SCRATCH_DIR`   | `~/sublime-scratch`          | `dump-untitled` default `--dir`  |
| `STO_SESSIONS_DIR`  | `~/.sto/sessions`            | `save` / `restore` / `sessions`  |
| `STO_PLUGIN_DIR`    | macOS Packages/User          | `install.sh` destination         |
| `STO_CLI_DIR`       | `~/.local/bin`               | `install.sh` destination         |

## caveats

- macOS paths in `install.sh` — override with `STO_PLUGIN_DIR` on Linux/Windows.
- Plugin binds to `127.0.0.1` only, no auth. Fine for personal use; avoid on shared machines.
- `sto close` on a dirty tab triggers ST's save dialog; CLI hangs until you answer. Use `--saved` or `--dry-run` to avoid.
- `sto recent` only tracks closes since the plugin loaded (no persistence across ST restarts).
- `sto find` does not support multiline patterns; ST's `find_all` is line-scoped.

## roadmap

- Linux/Windows `install.sh` paths.
- `sto find` with `--replace` for cross-buffer search/replace.
- Persist `recent` across ST restarts.
- Group-scoped sort (per-group instead of just active group).

## license

[MIT](./LICENSE) · [landing](https://gindachen.github.io/sublime-tab-organizer/) · [source](https://github.com/GindaChen/sublime-tab-organizer)
