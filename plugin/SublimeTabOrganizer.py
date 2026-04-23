"""
SublimeTabOrganizer — companion plugin.

Exposes a small JSON-line TCP server on 127.0.0.1:9998 so an external CLI
(`sto`) can list / close / merge / sort / dedupe tabs. ST API calls must run
on the main thread, so socket work happens on background threads and
dispatches commands back to the main thread via sublime.set_timeout.
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
VERSION = "0.1.0"

_server = None


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


def _cmd_close(args):
    ids = set(args.get("ids") or [])
    pattern = args.get("pattern")
    only_saved = bool(args.get("only_saved"))
    closed = []
    targeted = bool(ids or pattern or only_saved)
    if not targeted:
        return {"closed": [], "error": "close requires ids, --pattern, or --saved"}
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
            w.focus_view(v)
            w.run_command("close_file")
    return {"closed": closed}


def _copy_view_into(target_window, src_view):
    """Create a new view in target_window with src_view's text, name, syntax.

    ST has no cross-window move API (confirmed: set_view_index / set_sheet_index
    / move_sheets_to_group are all group-scoped). So we re-materialize the
    buffer. Caveats: undo history and view-local state (folds, bookmarks) are
    lost; file association is lost for dirty-with-path views.
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
    # `append` handles large inserts without requiring our own edit token.
    new_view.run_command("append", {"characters": text, "force": True, "scroll_to_end": False})
    return new_view


def _cmd_merge(args):
    target_id = args.get("target_window_id")
    copy_unsaved = bool(args.get("copy_unsaved"))
    target = None
    for w in sublime.windows():
        if target_id and w.id() == target_id:
            target = w
            break
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
                target.open_file(fn)
                moved.append(fn)
                v.close()
            elif copy_unsaved:
                new_view = _copy_view_into(target, v)
                copied.append({
                    "file": fn,
                    "name": v.name(),
                    "new_view_id": new_view.id(),
                    "was_dirty": is_dirty,
                    "was_untitled": fn is None,
                })
                # Suppress the save prompt for the source — we've already
                # preserved its contents in the target window.
                v.set_scratch(True)
                v.close()
            else:
                skipped.append({"file": fn, "reason": "dirty" if fn else "untitled"})
        if not w.views():
            try:
                w.run_command("close_window")
            except Exception:
                pass
    return {
        "moved": moved,
        "copied": copied,
        "skipped": skipped,
        "target_window_id": target.id(),
    }


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


def _cmd_dedupe(_args):
    seen = {}
    removed = []
    for w in sublime.windows():
        for v in list(w.views()):
            fn = v.file_name()
            if not fn:
                continue
            if fn in seen:
                removed.append(fn)
                w.focus_view(v)
                w.run_command("close_file")
            else:
                seen[fn] = v.id()
    return {"removed": removed}


def _cmd_group_by_folder(_args):
    """Keep the active window; move tabs whose file lives under a different
    top-level project folder into their own new windows."""
    src = sublime.active_window()
    if src is None:
        return {"error": "no active window"}
    folders = src.folders()
    if not folders:
        return {"error": "active window has no project folders to group by"}

    buckets = {}  # folder -> [file, ...]
    keep = []
    for v in list(src.views()):
        fn = v.file_name()
        if not fn or v.is_dirty():
            keep.append(v)
            continue
        match = None
        for f in folders:
            if fn.startswith(f.rstrip(os.sep) + os.sep):
                match = f
                break
        if match is None or match == folders[0]:
            keep.append(v)
        else:
            buckets.setdefault(match, []).append(fn)
            v.close()

    opened = {}
    for folder, files in buckets.items():
        sublime.run_command("new_window")
        nw = sublime.active_window()
        # attach folder as project
        proj = {"folders": [{"path": folder}]}
        nw.set_project_data(proj)
        for fn in files:
            nw.open_file(fn)
        opened[folder] = files
    # refocus original
    src.bring_to_front() if hasattr(src, "bring_to_front") else None
    return {"grouped": opened}


_SYNTAX_EXT = {
    "Python": "py",
    "JavaScript": "js",
    "TypeScript": "ts",
    "TSX": "tsx",
    "JSX": "jsx",
    "Markdown": "md",
    "MultiMarkdown": "md",
    "JSON": "json",
    "YAML": "yaml",
    "HTML": "html",
    "CSS": "css",
    "SCSS": "scss",
    "Shell Script (Bash)": "sh",
    "Shell Script": "sh",
    "Bash": "sh",
    "SQL": "sql",
    "Go": "go",
    "Rust": "rs",
    "C": "c",
    "C++": "cpp",
    "Ruby": "rb",
    "PHP": "php",
    "XML": "xml",
    "Java": "java",
    "Kotlin": "kt",
    "Swift": "swift",
    "Lua": "lua",
    "Plain Text": "txt",
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
    """Map sha256(content) -> path for every file in dest, so we can skip
    writes when an identical file already exists (content-based dedup)."""
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
    """Return <dest>/<base>.<ext>, appending _2, _3... on collision."""
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
    include_dirty = bool(args.get("include_dirty"))  # also dump dirty-with-path buffers
    os.makedirs(dest, exist_ok=True)

    existing = _existing_content_index(dest)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    dumped = []
    skipped = []
    for w in sublime.windows():
        for v in list(w.views()):
            fn = v.file_name()
            if fn and not (include_dirty and v.is_dirty()):
                continue  # saved tabs aren't scratch; skip
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

            if open_saved and v.window() is not None:
                v.window().open_file(path)
            if close_source:
                v.set_scratch(True)
                v.close()

    return {"dumped": dumped, "skipped": skipped, "dir": dest}


def _cmd_ping(_args):
    return {"pong": True, "version": VERSION, "windows": len(sublime.windows())}


COMMANDS = {
    "list": _cmd_list,
    "close": _cmd_close,
    "merge": _cmd_merge,
    "sort": _cmd_sort,
    "dedupe": _cmd_dedupe,
    "group-by-folder": _cmd_group_by_folder,
    "dump-untitled": _cmd_dump_untitled,
    "ping": _cmd_ping,
}


def _dispatch(req):
    cmd = req.get("cmd")
    handler = COMMANDS.get(cmd)
    if handler is None:
        return {"error": "unknown cmd: %s" % cmd}
    return handler(req.get("args") or {})


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
            if not done.wait(timeout=15):
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
