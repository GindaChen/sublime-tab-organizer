"""
SublimeTabOrganizer — companion plugin.

Exposes a JSON-line TCP server on 127.0.0.1:9998 so an external CLI (`sto`)
can drive window/tab operations. ST API calls must run on the main thread,
so socket work happens on background threads and dispatches back to the main
thread via sublime.set_timeout.

Also exposes `WindowCommand` subclasses so the same handlers appear in the
Sublime command palette (see Default.sublime-commands).
"""

import datetime
import fnmatch
import hashlib
import json
import os
import re
import socket
import threading

import sublime
import sublime_plugin

HOST = "127.0.0.1"
PORT = 9998
VERSION = "0.2.0"
RECENT_CAP = 100

_server = None
_recent = []  # ring buffer of {file, closed_at, window_id}


# ---------------------------------------------------------------- helpers

def _view_info(view):
    fn = view.file_name()
    w = view.window()
    return {
        "id": view.id(),
        "window_id": w.id() if w else None,
        "file": fn,
        "name": view.name() or (os.path.basename(fn) if fn else "untitled"),
        "dirty": view.is_dirty(),
        "scratch": view.is_scratch(),
        "size": view.size(),
    }


def _copy_view_into(target_window, src_view):
    """Re-materialize src_view inside target_window (ST has no move-view API).

    Text and syntax survive; undo history and view-local state (folds,
    bookmarks) do not; file association is lost for dirty-with-path views.
    """
    new_view = target_window.new_file()
    try:
        syn = src_view.syntax()
        if syn is not None:
            new_view.assign_syntax(syn)
    except Exception:
        pass
    src_name = src_view.name()
    if src_name:
        new_view.set_name(src_name)
    elif src_view.file_name():
        new_view.set_name(os.path.basename(src_view.file_name()))
    text = src_view.substr(sublime.Region(0, src_view.size()))
    new_view.run_command("append", {"characters": text, "force": True, "scroll_to_end": False})
    return new_view


def _find_view_by_id(view_id):
    for w in sublime.windows():
        for v in w.views():
            if v.id() == view_id:
                return v, w
    return None, None


def _find_window_by_id(window_id):
    for w in sublime.windows():
        if w.id() == window_id:
            return w
    return None


# ---------------------------------------------------------------- list

def _cmd_list(_args):
    out = []
    active = sublime.active_window()
    for w in sublime.windows():
        out.append({
            "window_id": w.id(),
            "active": active is not None and w.id() == active.id(),
            "folders": w.folders(),
            "views": [_view_info(v) for v in w.views()],
        })
    return {"windows": out}


# ---------------------------------------------------------------- close

def _cmd_close(args):
    ids = set(args.get("ids") or [])
    pattern = args.get("pattern")
    only_saved = bool(args.get("only_saved"))
    dry_run = bool(args.get("dry_run"))
    if not (ids or pattern or only_saved):
        return {"error": "close requires ids, --pattern, or --saved"}
    closed = []
    for w in sublime.windows():
        for v in list(w.views()):
            match = False
            if ids and v.id() in ids:
                match = True
            if pattern and v.file_name() and fnmatch.fnmatch(v.file_name(), pattern):
                match = True
            if only_saved and not v.is_dirty() and v.file_name():
                match = True
            if not match:
                continue
            if only_saved and v.is_dirty():
                continue
            closed.append(_view_info(v))
            if not dry_run:
                w.focus_view(v)
                w.run_command("close_file")
    return {"closed": closed, "dry_run": dry_run}


# ---------------------------------------------------------------- merge

def _cmd_merge(args):
    target_id = args.get("target_window_id")
    copy_unsaved = bool(args.get("copy_unsaved"))
    dry_run = bool(args.get("dry_run"))
    target = _find_window_by_id(target_id) if target_id else None
    if target is None:
        target = sublime.active_window()
    if target is None:
        return {"error": "no active window"}
    moved = []
    copied = []
    skipped = []
    for w in list(sublime.windows()):
        if w.id() == target.id():
            continue
        for v in list(w.views()):
            fn = v.file_name()
            is_dirty = v.is_dirty()
            if fn and not is_dirty:
                if not dry_run:
                    target.open_file(fn)
                    v.close()
                moved.append(fn)
            elif copy_unsaved:
                info = {
                    "file": fn,
                    "name": v.name(),
                    "was_dirty": is_dirty,
                    "was_untitled": fn is None,
                }
                if not dry_run:
                    new_view = _copy_view_into(target, v)
                    info["new_view_id"] = new_view.id()
                    v.set_scratch(True)
                    v.close()
                copied.append(info)
            else:
                skipped.append({"file": fn, "reason": "dirty" if fn else "untitled"})
        if not dry_run and not w.views():
            try:
                w.run_command("close_window")
            except Exception:
                pass
    return {
        "moved": moved,
        "copied": copied,
        "skipped": skipped,
        "target_window_id": target.id(),
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------- move (single tab)

def _cmd_move(args):
    view_id = args.get("view_id")
    target_id = args.get("target_window_id")
    dry_run = bool(args.get("dry_run"))
    if view_id is None or target_id is None:
        return {"error": "move requires view_id and target_window_id"}
    src_view, src_window = _find_view_by_id(int(view_id))
    if src_view is None:
        return {"error": "view %s not found" % view_id}
    target = _find_window_by_id(int(target_id))
    if target is None:
        return {"error": "window %s not found" % target_id}
    if src_window.id() == target.id():
        return {"error": "source and target are the same window"}
    fn = src_view.file_name()
    is_dirty = src_view.is_dirty()
    info = _view_info(src_view)
    method = "reopen" if (fn and not is_dirty) else "copy-contents"
    if dry_run:
        return {"moved": info, "method": method, "target_window_id": target.id(), "dry_run": True}
    if fn and not is_dirty:
        target.open_file(fn)
        src_view.close()
    else:
        _copy_view_into(target, src_view)
        src_view.set_scratch(True)
        src_view.close()
    return {"moved": info, "method": method, "target_window_id": target.id()}


# ---------------------------------------------------------------- sort

def _cmd_sort(args):
    by = args.get("by", "name")
    w = sublime.active_window()
    if w is None:
        return {"error": "no active window"}
    group = w.active_group()
    views = list(w.views_in_group(group))

    def key(v):
        fn = v.file_name() or v.name() or ""
        if by == "path":
            return fn.lower()
        if by == "ext":
            return (os.path.splitext(fn)[1].lower(), fn.lower())
        return os.path.basename(fn).lower()

    views.sort(key=key)
    for i, v in enumerate(views):
        w.set_view_index(v, group, i)
    return {"sorted": [_view_info(v) for v in views], "by": by}


# ---------------------------------------------------------------- dedupe

def _cmd_dedupe(args):
    dry_run = bool(args.get("dry_run"))
    seen = {}
    removed = []
    for w in sublime.windows():
        for v in list(w.views()):
            fn = v.file_name()
            if not fn:
                continue
            if fn in seen:
                removed.append(fn)
                if not dry_run:
                    w.focus_view(v)
                    w.run_command("close_file")
            else:
                seen[fn] = v.id()
    return {"removed": removed, "dry_run": dry_run}


# ---------------------------------------------------------------- group-by-folder

def _cmd_group_by_folder(_args):
    src = sublime.active_window()
    if src is None:
        return {"error": "no active window"}
    folders = src.folders()
    if not folders:
        return {"error": "active window has no project folders to group by"}

    buckets = {}
    for v in list(src.views()):
        fn = v.file_name()
        if not fn or v.is_dirty():
            continue
        match = None
        for f in folders:
            if fn.startswith(f.rstrip(os.sep) + os.sep):
                match = f
                break
        if match is None or match == folders[0]:
            continue
        buckets.setdefault(match, []).append(fn)
        v.close()

    opened = {}
    for folder, files in buckets.items():
        sublime.run_command("new_window")
        nw = sublime.active_window()
        nw.set_project_data({"folders": [{"path": folder}]})
        for fn in files:
            nw.open_file(fn)
        opened[folder] = files
    return {"grouped": opened}


# ---------------------------------------------------------------- dump-untitled

_SYNTAX_EXT = {
    "Python": "py", "JavaScript": "js", "TypeScript": "ts", "TSX": "tsx",
    "JSX": "jsx", "Markdown": "md", "MultiMarkdown": "md", "JSON": "json",
    "YAML": "yaml", "HTML": "html", "CSS": "css", "SCSS": "scss",
    "Shell Script (Bash)": "sh", "Shell Script": "sh", "Bash": "sh",
    "SQL": "sql", "Go": "go", "Rust": "rs", "C": "c", "C++": "cpp",
    "Ruby": "rb", "PHP": "php", "XML": "xml", "Java": "java",
    "Kotlin": "kt", "Swift": "swift", "Lua": "lua", "Plain Text": "txt",
}


def _ext_for(view):
    try:
        syn = view.syntax()
        if syn is not None:
            name = getattr(syn, "name", "") or ""
            if name in _SYNTAX_EXT:
                return _SYNTAX_EXT[name]
    except Exception:
        pass
    return "txt"


_SLUG_COMMENT_PREFIX = re.compile(r"^[#/*\-=;<>!\s]+")
_SLUG_NON_WORD = re.compile(r"[^\w\s-]")
_SLUG_WHITESPACE = re.compile(r"\s+")


def _slug(text, maxlen=40):
    first = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            first = stripped
            break
    if not first:
        return "untitled"
    first = _SLUG_COMMENT_PREFIX.sub("", first)
    first = _SLUG_NON_WORD.sub(" ", first)
    slug = _SLUG_WHITESPACE.sub("-", first.strip()).lower()
    slug = slug[:maxlen].strip("-")
    return slug or "untitled"


def _existing_content_index(dest):
    idx = {}
    try:
        for name in os.listdir(dest):
            path = os.path.join(dest, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                idx[h] = path
            except Exception:
                continue
    except FileNotFoundError:
        pass
    return idx


def _unique_path(dest, base, ext):
    path = os.path.join(dest, "%s.%s" % (base, ext))
    if not os.path.exists(path):
        return path
    i = 2
    while True:
        path = os.path.join(dest, "%s_%d.%s" % (base, i, ext))
        if not os.path.exists(path):
            return path
        i += 1


def _cmd_dump_untitled(args):
    dest = args.get("dir")
    if not dest:
        return {"error": "no dir provided"}
    dest = os.path.expanduser(dest)
    close_source = bool(args.get("close_source"))
    open_saved = bool(args.get("open_saved"))
    include_dirty = bool(args.get("include_dirty"))
    dry_run = bool(args.get("dry_run"))
    if not dry_run:
        os.makedirs(dest, exist_ok=True)

    existing = _existing_content_index(dest) if os.path.isdir(dest) else {}
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    dumped = []
    skipped = []
    for w in sublime.windows():
        for v in list(w.views()):
            fn = v.file_name()
            if fn and not (include_dirty and v.is_dirty()):
                continue
            text = v.substr(sublime.Region(0, v.size()))
            if not text.strip():
                skipped.append({"view_id": v.id(), "reason": "empty"})
                continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            reused = False
            if content_hash in existing:
                path = existing[content_hash]
                reused = True
            else:
                slug = _slug(text)
                ext = _ext_for(v)
                path = _unique_path(dest, "%s_%s" % (ts, slug), ext)
                if not dry_run:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                existing[content_hash] = path

            dumped.append({
                "view_id": v.id(),
                "path": path,
                "reused_existing": reused,
                "was_dirty": v.is_dirty(),
                "was_untitled": fn is None,
                "bytes": len(text.encode("utf-8")),
            })

            if not dry_run:
                if open_saved and v.window() is not None:
                    v.window().open_file(path)
                if close_source:
                    v.set_scratch(True)
                    v.close()

    return {"dumped": dumped, "skipped": skipped, "dir": dest, "dry_run": dry_run}


# ---------------------------------------------------------------- find

def _cmd_find(args):
    pattern = args.get("pattern")
    if not pattern:
        return {"error": "pattern required"}
    use_regex = bool(args.get("regex"))
    case_sensitive = bool(args.get("case_sensitive"))
    max_per_view = int(args.get("max_per_view") or 50)

    sf = 0
    if not use_regex:
        sf |= sublime.LITERAL
    if not case_sensitive:
        sf |= sublime.IGNORECASE

    results = []
    total = 0
    for w in sublime.windows():
        for v in w.views():
            try:
                regions = v.find_all(pattern, sf)
            except Exception as e:
                return {"error": "bad pattern: %s" % e}
            if not regions:
                continue
            view_matches = []
            for r in regions[:max_per_view]:
                row, col = v.rowcol(r.begin())
                line = v.substr(v.line(r))
                view_matches.append({
                    "row": row + 1,
                    "col": col + 1,
                    "text": line.strip()[:200],
                })
            fn = v.file_name()
            results.append({
                "view_id": v.id(),
                "window_id": w.id(),
                "file": fn,
                "name": v.name() or (os.path.basename(fn) if fn else "untitled"),
                "count": len(regions),
                "shown": len(view_matches),
                "matches": view_matches,
            })
            total += len(regions)
    return {"pattern": pattern, "results": results, "total_matches": total}


# ---------------------------------------------------------------- save-all

def _cmd_save_all(args):
    dry_run = bool(args.get("dry_run"))
    saved = []
    skipped = []
    for w in sublime.windows():
        for v in list(w.views()):
            if not v.is_dirty():
                continue
            fn = v.file_name()
            if not fn:
                skipped.append({"view_id": v.id(), "reason": "untitled"})
                continue
            saved.append({"view_id": v.id(), "file": fn})
            if not dry_run:
                w.focus_view(v)
                w.run_command("save")
    return {"saved": saved, "skipped": skipped, "dry_run": dry_run}


# ---------------------------------------------------------------- reload

def _cmd_reload(args):
    pattern = args.get("pattern")
    ids = set(args.get("ids") or [])
    dry_run = bool(args.get("dry_run"))
    if not (pattern or ids):
        return {"error": "reload requires --pattern or ids"}
    reloaded = []
    for w in sublime.windows():
        for v in list(w.views()):
            fn = v.file_name()
            if not fn:
                continue
            match = False
            if ids and v.id() in ids:
                match = True
            if pattern and fnmatch.fnmatch(fn, pattern):
                match = True
            if not match:
                continue
            reloaded.append({"view_id": v.id(), "file": fn})
            if not dry_run:
                w.focus_view(v)
                w.run_command("revert")
    return {"reloaded": reloaded, "dry_run": dry_run}


# ---------------------------------------------------------------- recent

class _RecentListener(sublime_plugin.EventListener):
    def on_close(self, view):
        fn = view.file_name()
        if not fn:
            return
        try:
            _recent.append({
                "file": fn,
                "closed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "window_id": None,  # view.window() is already None here
            })
        except Exception:
            return
        if len(_recent) > RECENT_CAP:
            del _recent[:len(_recent) - RECENT_CAP]


def _cmd_recent(args):
    action = args.get("action") or "list"
    if action == "list":
        limit = int(args.get("limit") or 20)
        rev = list(reversed(_recent))
        return {"recent": rev[:limit]}
    if action == "clear":
        _recent.clear()
        return {"cleared": True}
    if action == "restore":
        target_file = args.get("file")
        idx = args.get("index")
        if target_file is None and idx is not None:
            rev = list(reversed(_recent))
            try:
                idx = int(idx)
            except Exception:
                return {"error": "index must be int"}
            if idx < 0 or idx >= len(rev):
                return {"error": "index out of range (0..%d)" % (len(rev) - 1)}
            target_file = rev[idx]["file"]
        if not target_file:
            return {"error": "recent restore needs --index or --file"}
        if not os.path.exists(target_file):
            return {"error": "file no longer exists: %s" % target_file}
        w = sublime.active_window()
        if w is None:
            return {"error": "no active window"}
        w.open_file(target_file)
        return {"restored": target_file}
    return {"error": "unknown action: %s (use list/restore/clear)" % action}


# ---------------------------------------------------------------- sessions

def _cmd_session_save(args):
    include_contents = args.get("include_untitled_contents", True)
    active = sublime.active_window()
    windows = []
    for w in sublime.windows():
        groups = []
        for gi in range(w.num_groups()):
            gviews = []
            active_in_group = w.active_view_in_group(gi)
            for v in w.views_in_group(gi):
                entry = {}
                fn = v.file_name()
                if fn:
                    entry["file"] = fn
                else:
                    if not include_contents:
                        continue
                    entry["contents"] = v.substr(sublime.Region(0, v.size()))
                    try:
                        syn = v.syntax()
                        if syn:
                            entry["syntax"] = syn.path
                    except Exception:
                        pass
                    if v.name():
                        entry["name"] = v.name()
                if active_in_group and v.id() == active_in_group.id():
                    entry["active"] = True
                gviews.append(entry)
            groups.append({"views": gviews})
        windows.append({
            "active": active is not None and w.id() == active.id(),
            "folders": w.folders(),
            "groups": groups,
        })
    return {
        "version": 1,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "windows": windows,
    }


def _cmd_session_restore(args):
    data = args.get("session")
    if not isinstance(data, dict):
        return {"error": "no session data provided"}
    close_existing = bool(args.get("close_existing"))
    opened = []
    if close_existing:
        for w in list(sublime.windows()):
            for v in list(w.views()):
                if v.is_dirty():
                    v.set_scratch(True)
                v.close()
    windows_data = data.get("windows", [])
    for i, wd in enumerate(windows_data):
        if i == 0:
            nw = sublime.active_window()
            if nw is None:
                sublime.run_command("new_window")
                nw = sublime.active_window()
        else:
            sublime.run_command("new_window")
            nw = sublime.active_window()
        if nw is None:
            continue
        folders = wd.get("folders") or []
        if folders:
            nw.set_project_data({"folders": [{"path": f} for f in folders]})
        for group in wd.get("groups", []):
            for vd in group.get("views", []):
                fn = vd.get("file")
                if fn and os.path.exists(fn):
                    nw.open_file(fn)
                    opened.append(fn)
                elif "contents" in vd:
                    new_view = nw.new_file()
                    syn_path = vd.get("syntax")
                    if syn_path:
                        try:
                            new_view.assign_syntax(syn_path)
                        except Exception:
                            pass
                    if vd.get("name"):
                        new_view.set_name(vd["name"])
                    new_view.run_command("append", {
                        "characters": vd["contents"],
                        "force": True, "scroll_to_end": False,
                    })
                    opened.append("<untitled>")
    return {"opened": opened, "windows": len(windows_data)}


# ---------------------------------------------------------------- ping

def _cmd_ping(_args):
    return {"pong": True, "version": VERSION, "windows": len(sublime.windows())}


# ---------------------------------------------------------------- dispatch

COMMANDS = {
    "list": _cmd_list,
    "close": _cmd_close,
    "merge": _cmd_merge,
    "move": _cmd_move,
    "sort": _cmd_sort,
    "dedupe": _cmd_dedupe,
    "group-by-folder": _cmd_group_by_folder,
    "dump-untitled": _cmd_dump_untitled,
    "find": _cmd_find,
    "save-all": _cmd_save_all,
    "reload": _cmd_reload,
    "recent": _cmd_recent,
    "session-save": _cmd_session_save,
    "session-restore": _cmd_session_restore,
    "ping": _cmd_ping,
}


def _dispatch(req):
    cmd = req.get("cmd")
    handler = COMMANDS.get(cmd)
    if handler is None:
        return {"error": "unknown cmd: %s" % cmd}
    return handler(req.get("args") or {})


# ---------------------------------------------------------------- TCP server

class _Server(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = None
        self._stop = threading.Event()

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
        except OSError as e:
            print("[STO] bind %s:%d failed: %s" % (HOST, PORT, e))
            return
        s.listen(5)
        self.sock = s
        print("[STO] listening on %s:%d" % (HOST, PORT))
        while not self._stop.is_set():
            try:
                conn, _ = s.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(5)
            # Large payloads (session-restore) may span many packets.
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            line = buf.decode("utf-8").strip()
            if not line:
                return
            req = json.loads(line)

            holder = {}
            done = threading.Event()

            def run_on_main():
                try:
                    holder["result"] = _dispatch(req)
                except Exception as e:
                    holder["error"] = "%s: %s" % (type(e).__name__, e)
                done.set()

            sublime.set_timeout(run_on_main, 0)
            # session-restore can take a while on large sessions.
            if not done.wait(timeout=30):
                resp = {"error": "timeout waiting for main thread"}
            elif "error" in holder:
                resp = {"error": holder["error"]}
            else:
                resp = {"result": holder["result"]}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception as e:
            try:
                conn.sendall((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


def plugin_loaded():
    global _server
    _server = _Server()
    _server.start()


def plugin_unloaded():
    global _server
    if _server is not None:
        _server.stop()
        _server = None


# ---------------------------------------------------------------- palette wrappers

def _status(cmd, result):
    if "error" in result:
        sublime.status_message("sto %s: %s" % (cmd, result["error"]))
    else:
        # Pick a concise one-line summary per command.
        msg = "sto %s: ok" % cmd
        if cmd == "merge":
            msg = "sto merge: %d moved, %d copied, %d skipped" % (
                len(result.get("moved", [])),
                len(result.get("copied", [])),
                len(result.get("skipped", [])),
            )
        elif cmd == "dedupe":
            msg = "sto dedupe: %d removed" % len(result.get("removed", []))
        elif cmd == "dump-untitled":
            msg = "sto dump-untitled: %d files" % len(result.get("dumped", []))
        elif cmd == "save-all":
            msg = "sto save-all: %d saved" % len(result.get("saved", []))
        elif cmd == "sort":
            msg = "sto sort: %d tabs" % len(result.get("sorted", []))
        sublime.status_message(msg)


class StoMergeCommand(sublime_plugin.WindowCommand):
    def run(self, copy_unsaved=True):
        _status("merge", _cmd_merge({"copy_unsaved": copy_unsaved}))


class StoDedupeCommand(sublime_plugin.WindowCommand):
    def run(self):
        _status("dedupe", _cmd_dedupe({}))


class StoSortCommand(sublime_plugin.WindowCommand):
    def run(self, by="name"):
        _status("sort", _cmd_sort({"by": by}))


class StoDumpUntitledCommand(sublime_plugin.WindowCommand):
    def run(self, dir=None, close_source=False, open_saved=False):
        _status("dump-untitled", _cmd_dump_untitled({
            "dir": dir or "~/sublime-scratch",
            "close_source": close_source,
            "open_saved": open_saved,
        }))


class StoSaveAllCommand(sublime_plugin.WindowCommand):
    def run(self):
        _status("save-all", _cmd_save_all({}))


class StoGroupByFolderCommand(sublime_plugin.WindowCommand):
    def run(self):
        _status("group-by-folder", _cmd_group_by_folder({}))
