"""
[written primarily by claude]

Two-column Textual file browser with a recursive filter and extension-based previews.

Usage:  python cli.py [ROOT_DIR] [--meta-key fxt-data-schema --meta-key "fxt-data*" ...]
        or from code: FileBrowserApp(root, metadata_keys=["fxt-data-schema", "fxt-data*"]).run()
Deps:   textual (required), polars (optional, for .parquet previews)

- Empty filter  -> normal lazy DirectoryTree (allowed extensions only).
- Typed filter  -> searches an index of the WHOLE tree (built once in a background
                   thread) and shows only matching files, with their folders expanded.
                   Space-separated terms must all appear in the relative path,
                   e.g. "eurusd 2024 parquet".

- ctrl+s        -> saves the root, open file and filter to settings.toml next to this
                   script; they're restored on the next launch. The theme (change it
                   from the ctrl+p palette) is saved automatically.

- ctrl+b        -> bookmark the open file, with an optional name (again to rename).
- ctrl+o        -> bookmarks menu: Enter opens, r renames, d deletes.
- New file type -> subclass BasePreview (set `extensions`, implement `build()`);
                   it's registered automatically and its files appear in the tree.

- [defaults]    -> settings.toml can set a default folder and metadata keys:
                   [defaults]
                   root = "data/"
                   meta_keys = ["fxt-data:type", "fxt-data*"]

                   
Use:
    meta_keys = ["fxt-data:type", "fxt-data*"]

cuz that shows the type string first, then shows all other keys with the fxt-data
prefix.
                
"""
from __future__ import annotations

import csv
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, ClassVar#, Iterable
from collections.abc import Iterable

from rich.console import Group
from rich.syntax import Syntax
from rich.table import Table as RichTable
from rich.text import Text
from textual import on, work
from textual.worker import get_current_worker
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    Static,
    Tree,
)
from textual.widgets.option_list import Option

# Which files appear in the tree is decided by the registered previews: see BasePreview.
SKIP_DIRS = {"__pycache__", "node_modules", ".pixi", ".venv", ".git"}

MAX_RESULTS = 2_000   # cap filter results so a broad query stays snappy

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.toml"


# ---------- settings ----------

def load_settings(path: Path) -> dict[str, Any]:
    """Read settings.toml; a missing or broken file just means no settings."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


SETTINGS_TEMPLATE = """\
# file_browser settings.
# [defaults] is yours to edit. [location] (ctrl+s), [ui] (theme) and [bookmarks]
# are rewritten by the app; the rest of this file, comments included, is left alone.

[defaults]
# Folder to open when none is given on the command line and no location is saved.
# root = "~/datalake"

# Parquet metadata keys to show, in this order. Exact names or globs ("fxt-data*").
# A key matched by an earlier entry isn't shown twice.
# meta_keys = ["fxt-data-schema", "fxt-data*"]
"""


def toml_key(key: str) -> str:
    """Bare key if TOML allows it, otherwise a quoted one (e.g. a file path)."""
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def toml_value(value: Any) -> str:
    """Encode a scalar or list of scalars as TOML. JSON string escapes are valid TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


_TABLE_HEADER = re.compile(r"^\s*(\[\[?)\s*([^\[\]]+?)\s*\]\]?\s*(#.*)?$")


def _drop_table(text: str, table: str) -> str:
    """Remove a top-level [table] block (header up to the next table header)."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        m = _TABLE_HEADER.match(line.rstrip("\r\n"))
        if m:
            skipping = m.group(1) == "[" and m.group(2) == table
        if not skipping:
            out.append(line)
    return "".join(out)


def save_settings(path: Path, updates: dict[str, dict[str, Any]]) -> None:
    """Merge `updates` ({table: {key: value}}) into the settings file.

    Only the tables being updated are rewritten (moved to the end of the file);
    everything else, comments included, is left exactly as it was. A value of None
    removes that key. Raises on a file with a syntax error rather than overwriting it.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else SETTINGS_TEMPLATE
    current = tomllib.loads(text)  # raises if the user's edits broke the file

    for table, values in updates.items():
        merged = {**current.get(table, {}), **values}
        text = _drop_table(text, table).rstrip() + "\n"
        items = [(k, v) for k, v in merged.items() if v is not None]
        if items:
            text += f"\n[{table}]\n" + "".join(f"{toml_key(k)} = {toml_value(v)}\n" for k, v in items)

    tomllib.loads(text)  # sanity check before touching the real file
    tmp = path.with_suffix(".tmp")  # write-then-rename so a crash can't truncate it
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------- indexing ----------

def scan(root: Path, extensions: set[str]) -> list[str]:
    """Return relative paths (as strings) of all allowed files under root."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune in place so os.walk never descends into skipped dirs.
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
        )
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            if name.startswith(".") or os.path.splitext(name)[1].lower() not in extensions:
                continue
            found.append(name if rel_dir == "." else os.path.join(rel_dir, name))
    return found


class FilteredDirectoryTree(DirectoryTree):
    """Lazy DirectoryTree showing only allowed extensions (no text filter)."""

    def __init__(self, path: str | Path, extensions: set[str], **kwargs) -> None:
        super().__init__(path, **kwargs)
        self.extensions = extensions

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for path in paths:
            if path.name.startswith(".") or path.name in SKIP_DIRS:
                continue
            if path.is_dir() or path.suffix.lower() in self.extensions:
                yield path

    async def reveal(self, path: Path) -> None:
        """Expand the folders leading to `path` and put the cursor on it."""
        try:
            parts = path.relative_to(self.path).parts
        except ValueError:
            return
        node = self.root
        for part in parts:
            await self._add_to_load_queue(node)  # no-op if already loaded; waits otherwise
            node.expand()
            node = next(
                (c for c in node.children if c.data and c.data.path.name == part), None
            )
            if node is None:
                return
        self.move_cursor(node)
        self.scroll_to_node(node, animate=False)


# ---------- preview helpers ----------

def fmt(value: object) -> str:
    """Show floats at full useful precision (prices need 5 dp, DataTable shows 2)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def pretty_json(raw: str) -> str | None:
    """Pretty-print raw if it's a JSON object/array, else None."""
    raw = raw.strip()
    if raw[:1] not in "{[":
        return None
    try:
        return json.dumps(json.loads(raw), indent=2)
    except ValueError:
        return None


def section(title: str, body: Widget) -> Widget:
    """Wrap a widget in a bordered, titled box (the CSS for .section lives on the app)."""
    body.add_class("section")
    body.border_title = title
    return body


def system_copy(text: str) -> str | None:
    """Copy via the desktop's clipboard tool. Returns the tool used, or None.

    Textual's own copy_to_clipboard uses the OSC 52 escape code, which some
    terminals ignore (or only allow after a setting), so this is the reliable path
    on a local desktop.
    """
    commands: list[tuple[str, ...]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(("wl-copy",))
    if os.environ.get("DISPLAY"):
        commands += [("xclip", "-selection", "clipboard"), ("xsel", "--clipboard", "--input")]
    if sys.platform == "darwin":
        commands.append(("pbcopy",))
    for cmd in commands:
        if not shutil.which(cmd[0]):
            continue
        try:
            # DEVNULL matters: wl-copy/xclip leave a child running to serve the
            # clipboard, and a piped stdout would make run() wait on it.
            subprocess.run(
                cmd, input=text.encode(), check=True, timeout=3,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return cmd[0]
        except (OSError, subprocess.SubprocessError):
            continue
    return None


class CopyableSection(Vertical):
    """A titled section box with a Copy button that copies `copy_text`."""

    DEFAULT_CSS = """
    CopyableSection { height: auto; }
    CopyableSection > .copy-bar { height: 1; align-horizontal: right; }
    CopyableSection Button.copy {
        height: 1; min-width: 8; padding: 0 1; border: none;
    }
    """

    def __init__(self, title: str, body: Widget, copy_text: str) -> None:
        super().__init__(
            Horizontal(Button("Copy", classes="copy", compact=True), classes="copy-bar"),
            body,
            classes="section",
        )
        self.border_title = title
        self.copy_text = copy_text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        app = self.app
        app.copy_to_clipboard(self.copy_text)  # OSC 52: also works over SSH
        via = system_copy(self.copy_text)
        what = self.border_title or "section"
        if via:
            app.notify(f"Copied {what}", timeout=2)
        else:
            app.notify(
                f"Sent {what} to the terminal clipboard. If paste is empty, install "
                "wl-clipboard (Wayland) or xclip (X11).",
                timeout=5,
            )


class RowsTable(DataTable):
    """DataTable that takes its data up front and fills itself once mounted.

    DataTable needs the running app to measure columns, so it can't be populated
    on a worker thread. Building this on the thread and filling it in on_mount
    keeps all file I/O off the UI thread.
    """

    def __init__(self, columns: list[str], rows: Iterable[tuple], **kwargs) -> None:
        super().__init__(zebra_stripes=True, **kwargs)
        self._columns = columns
        self._rows = [tuple(fmt(v) for v in row) for row in rows]

    def on_mount(self) -> None:
        self.add_columns(*self._columns)
        self.add_rows(self._rows)


# ---------- previews ----------

@dataclass(frozen=True)
class PreviewContext:
    """App-level options handed to every preview. Add fields as previews need them."""

    metadata_keys: tuple[str, ...] = ()  # parquet metadata keys/globs to show, in order


class BasePreview(ABC):
    """Builds the widget shown in the preview pane for one file.

    To add a file type, subclass this, set `extensions` and implement `build()`.
    Defining the subclass registers it: its extensions show up in the file tree and
    selecting one of those files uses it. A later subclass that claims the same
    extension replaces the earlier one, so you can override a built-in preview.

    Threading: `build()` runs on a worker thread, so do the file I/O there, but
    don't query or change the app. Widgets that need the running app (DataTable)
    should take their data in __init__ and fill themselves in on_mount (see RowsTable).
    """

    extensions: ClassVar[tuple[str, ...]] = ()
    max_bytes: ClassVar[int] = 200_000  # cap for read_text()

    _registry: ClassVar[dict[str, type[BasePreview]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for ext in cls.extensions:
            BasePreview._registry[ext.lower()] = cls

    def __init__(self, path: Path, context: PreviewContext | None = None) -> None:
        self.path = path
        self.context = context or PreviewContext()

    @abstractmethod
    def build(self) -> Widget:
        """Return the widget (or container of widgets) for the preview pane."""

    def build_safely(self) -> Widget:
        """build(), but returns an error message instead of raising."""
        try:
            return self.build()
        except Exception as exc:
            return Static(Text(f"Could not preview {self.path.name}: {exc}", style="red"))

    def read_text(self) -> str:
        with self.path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(self.max_bytes)

    # --- registry ---

    @staticmethod
    def supported_extensions() -> set[str]:
        return set(BasePreview._registry)

    @staticmethod
    def for_path(path: Path, context: PreviewContext | None = None) -> BasePreview:
        """The registered preview for this file's extension (plain text if none)."""
        preview_cls = BasePreview._registry.get(path.suffix.lower(), TextPreview)
        return preview_cls(path, context)


class TextPreview(BasePreview):
    extensions = (".txt",)

    def build(self) -> Widget:
        return Static(Text(self.read_text()))


class MarkdownPreview(BasePreview):
    extensions = (".md",)

    def build(self) -> Widget:
        return Markdown(self.read_text())


class CodePreview(BasePreview):
    LEXERS: ClassVar[dict[str, str]] = {
        ".py": "python",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".ex": "elixir",
        ".exs": "elixir",
    }
    extensions = tuple(LEXERS)

    def build(self) -> Widget:
        lexer = self.LEXERS[self.path.suffix.lower()]
        return Static(Syntax(self.read_text(), lexer, line_numbers=True, word_wrap=True))


class CSVPreview(BasePreview):
    extensions = (".csv",)
    max_rows: ClassVar[int] = 500

    def build(self) -> Widget:
        with self.path.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            width = len(header)
            rows = [
                tuple((row + [""] * width)[:width])  # pad/trim ragged rows
                for _, row in zip(range(self.max_rows), reader)
            ]
        return RowsTable(header, rows)


class ParquetPreview(BasePreview):
    """Stacked boxes: stats, any JSON (from a column or file metadata), first rows.

    Override `sections()` to reorder the boxes or add new ones.
    """

    extensions = (".parquet",)
    preview_rows: ClassVar[int] = 10
    # String columns checked first when looking for JSON in the data.
    json_columns: ClassVar[tuple[str, ...]] = ("metadata", "meta", "params", "config")

    def build(self) -> Widget:
        try:
            import polars as pl
        except ImportError:
            return Static("Install polars to preview .parquet files.")
        self.pl = pl
        self.lf = pl.scan_parquet(self.path)
        self.sample = self.lf.head(self.preview_rows).collect()
        try:
            self.meta: dict[str, str] = pl.read_parquet_metadata(self.path)
        except Exception:
            self.meta = {}
        return Vertical(*self.sections(), classes="stack")

    def sections(self) -> list[Widget]:
        return [self.stats_section(), *self.json_sections(), self.rows_section()]

    # --- sections ---

    def stats_section(self) -> Widget:
        """File-level facts plus per-column dtype / nulls / min / max."""
        pl, lf = self.pl, self.lf
        schema = lf.collect_schema()
        n_rows = lf.select(pl.len()).collect().item()

        summarisable = [c for c, t in schema.items() if t.is_numeric() or t.is_temporal()]
        agg = lf.select(
            *(pl.col(c).null_count().alias(f"{c}\0nulls") for c in schema),
            *(pl.col(c).min().alias(f"{c}\0min") for c in summarisable),
            *(pl.col(c).max().alias(f"{c}\0max") for c in summarisable),
        ).collect().row(0, named=True)

        table = RichTable(box=None, pad_edge=False, header_style="bold")
        for col in ("column", "dtype", "nulls", "min", "max"):
            table.add_column(col, justify="right" if col == "nulls" else "left")
        for c, t in schema.items():
            table.add_row(
                c, str(t), f"{agg[f'{c}\0nulls']:,}",
                fmt(agg.get(f"{c}\0min")), fmt(agg.get(f"{c}\0max")),
            )

        header = Text.assemble(
            ("Rows ", "dim"), f"{n_rows:,}   ",
            ("Columns ", "dim"), f"{len(schema)}   ",
            ("Size ", "dim"), human_size(self.path.stat().st_size), "\n",
        )
        return section("Stats", Static(Group(header, table)))

    def json_sections(self) -> list[Widget]:
        """JSON found in a data column, then the configured metadata keys."""
        out: list[Widget] = []
        from_column = self.json_from_columns()
        if from_column:
            title, pretty = from_column
            body = Static(Syntax(pretty, "json", line_numbers=True))
            out.append(CopyableSection(title, body, pretty))

        # Unconfigured, metadata_entries guesses one JSON key; skip that guess if a
        # data column already supplied the JSON section.
        keys = self.context.metadata_keys
        if keys or not from_column:
            for title, text, lexer in self.metadata_entries(keys):
                body = (
                    Syntax(text, lexer, line_numbers=True, word_wrap=True)
                    if lexer == "json" else Text(text)
                )
                out.append(CopyableSection(title, Static(body), text))
        return out

    def rows_section(self) -> Widget:
        table = RowsTable(self.sample.columns, self.sample.iter_rows(), cursor_type="row")
        return section(f"First {self.sample.height} rows", table)

    # --- lookups ---

    def json_from_columns(self) -> tuple[str, str] | None:
        """First JSON value found in a string column (json_columns checked first)."""
        string_cols = [c for c, t in self.sample.schema.items() if t == self.pl.String]
        ordered = [c for c in self.json_columns if c in string_cols] + [
            c for c in string_cols if c not in self.json_columns
        ]
        for col in ordered:
            values = self.sample.get_column(col).drop_nulls()
            if not values.is_empty() and (pretty := pretty_json(values[0])):
                return f"JSON · column '{col}', first row", pretty
        return None

    def metadata_entries(self, keys: tuple[str, ...]) -> list[tuple[str, str, str]]:
        """Pick file-metadata entries to show, as (title, text, lexer).

        `keys` is an ordered list of exact names or globs ("fxt-data*"); entries
        follow that order, and a glob's matches follow file order. A key already
        matched by an earlier entry is skipped; listed keys missing from the file
        are ignored. With no keys, falls back to the first value holding JSON.
        """
        meta = self.meta

        def entry(key: str) -> tuple[str, str, str]:
            pretty = pretty_json(meta[key])
            return f"Metadata · {key}", pretty or meta[key], "json" if pretty else "text"

        candidates = [k for k in meta if k != "ARROW:schema"]  # binary blob, not useful
        if not keys:
            first = next((k for k in candidates if pretty_json(meta[k])), None)
            return [entry(first)] if first else []

        shown: list[str] = []
        for pattern in keys:
            for key in candidates:
                if key not in shown and fnmatch.fnmatchcase(key, pattern):
                    shown.append(key)
        return [entry(k) for k in shown]


# ---------- bookmark screens ----------

class BookmarkNameScreen(ModalScreen[str | None]):
    """Asks for an optional bookmark name.

    Dismisses with the name ("" means no name) or None if cancelled.
    """

    DEFAULT_CSS = """
    BookmarkNameScreen { align: center middle; }
    BookmarkNameScreen > Vertical {
        width: 72; height: auto;
        border: round $primary; border-title-align: left;
        background: $surface; padding: 1 2;
    }
    BookmarkNameScreen .path { color: $text-muted; margin-bottom: 1; }
    BookmarkNameScreen .hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]  # noqa: RUF012

    def __init__(self, heading: str, path_label: str, name: str = "") -> None:
        super().__init__()
        self.heading = heading
        self.path_label = path_label
        self.initial_name = name

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.heading
            yield Label(self.path_label, classes="path")
            yield Input(value=self.initial_name, placeholder="Name (optional)")
            yield Label("Enter saves, Esc cancels", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class BookmarksScreen(ModalScreen[Path | None]):
    """Lists bookmarks. Dismisses with the chosen file's path, or None."""

    DEFAULT_CSS = """
    BookmarksScreen { align: center middle; }
    BookmarksScreen > Vertical {
        width: 90; height: auto; max-height: 80%;
        border: round $primary; border-title-align: left;
        background: $surface; padding: 1 2;
    }
    BookmarksScreen OptionList { height: auto; max-height: 30; padding: 0; }
    BookmarksScreen OptionList, BookmarksScreen OptionList:focus {
        border: none; background: transparent;
    }
    BookmarksScreen .hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [  # noqa: RUF012
        ("escape", "close", "Close"),
        ("r", "rename", "Rename"),
        ("d", "delete", "Delete"),
        ("delete", "delete", "Delete"),
    ]

    app: FileBrowserApp  # for type checkers

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "Bookmarks"
            yield OptionList(id="bookmark-list")
            yield Label("", id="bookmark-hint", classes="hint")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self, highlight: int | None = 0) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        for key, name in self.app.bookmarks.items():
            path = Path(key)
            prompt = Text(name or path.name, style="bold")
            prompt.append("\n" + self.app.display_path(path), style="dim")
            if not path.is_file():
                prompt.append("  (missing)", style="red")
            options.add_option(Option(prompt, id=key))

        hint = self.query_one("#bookmark-hint", Label)
        if options.option_count:
            options.highlighted = min(highlight or 0, options.option_count - 1)
            hint.update("Enter opens, r renames, d deletes, Esc closes")
        else:
            hint.update("No bookmarks yet. Open a file and press ctrl+b to add one.")

    def _highlighted(self) -> tuple[int, Path] | None:
        options = self.query_one(OptionList)
        if options.highlighted is None:
            return None
        option = options.get_option_at_index(options.highlighted)
        return options.highlighted, Path(option.id)   #type: ignore

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(Path(event.option.id))   #type: ignore

    def action_close(self) -> None:
        self.dismiss(None)

    def action_delete(self) -> None:
        if picked := self._highlighted():
            index, path = picked
            self.app.remove_bookmark(path)
            self.refresh_list(index)

    def action_rename(self) -> None:
        if not (picked := self._highlighted()):
            return
        index, path = picked

        def done(name: str | None) -> None:
            if name is not None:
                self.app.set_bookmark(path, name)
                self.refresh_list(index)

        self.app.push_screen(
            BookmarkNameScreen(
                "Rename bookmark", self.app.display_path(path), self.app.bookmarks.get(str(path), "")
            ),
            done,
        )


# ---------- app ----------

class FileBrowserApp(App):
    CSS = """
    #sidebar { width: 60; border-right: solid $primary; }
    #filter { margin-bottom: 1; }
    #switcher, #browse, #results { height: 1fr; }
    #preview { width: 1fr; padding: 0 1; }

    /* Parquet preview: a vertical stack of bordered sections, each sized to content */
    .stack { height: auto; }
    .section {
        height: auto;
        border: round $primary;
        border-title-align: left;
        padding: 0 1;
        margin-bottom: 1;
    }
    .stack DataTable { max-height: 14; }
    """

    BINDINGS = [  # noqa: RUF012
        ("ctrl+f", "focus_filter", "Filter"),
        ("ctrl+t", "focus_tree", "Tree"),
        ("ctrl+r", "reindex", "Re-index"),
        ("ctrl+s", "save_location", "Save location"),
        ("ctrl+b", "bookmark", "Bookmark"),
        ("ctrl+o", "bookmarks", "Bookmarks"),
        # Typing "q" in the filter box still types a q: Input consumes printable keys
        # before app bindings see them.
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        root: Path | None = None,
        metadata_keys: Iterable[str] | None = None,
        settings_path: Path = SETTINGS_PATH,
        metadata_prefixes: Iterable[str] = (),
    ) -> None:
        """
        root:              folder to browse; None -> saved location, then [defaults].root,
                           then the current directory.
        metadata_keys:     parquet metadata keys to show, in order (exact names or globs);
                           None -> [defaults].meta_keys from settings.toml.
        metadata_prefixes: shorthand kept from the earlier version; "fxt-data" is the
                           same as the glob "fxt-data*" appended to metadata_keys.
        """
        super().__init__()
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        location = self.settings.get("location", {})
        defaults = self.settings.get("defaults", {})

        def existing_dir(value: Any) -> Path | None:
            path = Path(value).expanduser() if isinstance(value, str) and value else None
            return path if path and path.is_dir() else None

        # Root: explicit argument > saved location > [defaults].root > current dir.
        saved_root = existing_dir(location.get("root"))
        if root is None:
            root = saved_root or existing_dir(defaults.get("root")) or Path.cwd()
        self.root = root.expanduser().resolve()

        # Only restore the file/filter if they were saved for this same root.
        same_root = saved_root is not None and saved_root.resolve() == self.root
        self._restore_filter = location.get("filter", "") if same_root else ""
        self._restore_file: Path | None = None
        if same_root and location.get("file"):
            candidate = self.root / location["file"]
            if candidate.is_file():
                self._restore_file = candidate

        # Explicit keys/prefixes replace the defaults rather than adding to them.
        keys = list(metadata_keys or []) + [f"{p}*" for p in metadata_prefixes]
        if metadata_keys is None and not metadata_prefixes:
            configured = defaults.get("meta_keys", [])
            keys = [configured] if isinstance(configured, str) else list(configured)
        self.preview_context = PreviewContext(metadata_keys=tuple(str(k) for k in keys))
        self.index: list[str] | None = None   # None until the background scan finishes
        self.filter_text = ""
        self.current_file: Path | None = None
        # Bookmarks: absolute path -> name ("" = unnamed), in the order they were added.
        self.bookmarks: dict[str, str] = {
            str(k): str(v) for k, v in self.settings.get("bookmarks", {}).items()
        }
        self._filter_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="Indexing…", id="filter")
                with ContentSwitcher(initial="browse", id="switcher"):
                    yield FilteredDirectoryTree(
                        self.root, BasePreview.supported_extensions(), id="browse"
                    )
                    yield Tree("results", id="results")
            yield VerticalScroll(Static("Select a file to preview it."), id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = str(self.root)
        self.query_one("#results", Tree).show_root = False

        theme = self.settings.get("ui", {}).get("theme")
        if theme in self.available_themes:
            self.theme = theme

        self.query_one("#browse").focus()
        if self._restore_filter:
            # Fills the box; apply_filter then runs via on_input_changed (and again
            # once the index is ready), highlighting the open file in the results.
            self.query_one("#filter", Input).value = self._restore_filter
        if self._restore_file:
            self.show_preview(self._restore_file)
            if not self._restore_filter:
                self.reveal_file(self._restore_file)
        self.build_index()

    @work(exclusive=True, group="reveal")
    async def reveal_file(self, path: Path) -> None:
        await self.query_one("#browse", FilteredDirectoryTree).reveal(path)

    def display_path(self, path: Path) -> str:
        """Path relative to the browsed folder if inside it, else with ~ for home."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            try:
                return "~/" + path.relative_to(Path.home()).as_posix()
            except ValueError:
                return str(path)

    # --- bookmarks ---

    def action_bookmark(self) -> None:
        path = self.current_file
        if path is None:
            self.notify("Open a file first, then press ctrl+b.", severity="warning")
            return
        key = str(path)
        exists = key in self.bookmarks

        def done(name: str | None) -> None:
            if name is not None and self.set_bookmark(path, name):
                verb = "Renamed bookmark" if exists else "Bookmarked"
                self.notify(f"{verb}: {name or path.name}", timeout=3)

        self.push_screen(
            BookmarkNameScreen(
                "Rename bookmark" if exists else "Add bookmark",
                self.display_path(path),
                self.bookmarks.get(key, ""),
            ),
            done,
        )

    def action_bookmarks(self) -> None:
        self.push_screen(BookmarksScreen(), self.open_bookmark)

    def set_bookmark(self, path: Path, name: str) -> bool:
        key = str(path)
        if self._write_settings({"bookmarks": {key: name}}):
            self.bookmarks[key] = name
            return True
        return False

    def remove_bookmark(self, path: Path) -> bool:
        key = str(path)
        if self._write_settings({"bookmarks": {key: None}}):
            self.bookmarks.pop(key, None)
            return True
        return False

    def open_bookmark(self, path: Path | None) -> None:
        if path is None:
            return
        if not path.is_file():
            self.notify(f"{self.display_path(path)} no longer exists.", severity="error")
            return
        self.show_preview(path)
        try:
            rel = path.relative_to(self.root).as_posix().lower()
        except ValueError:
            self.notify(f"That file is outside {self.root}, so it's only previewed.", timeout=4)
            return

        terms = self.filter_text.lower().split()
        if terms and all(t in rel for t in terms):
            self.apply_filter(self.filter_text)  # re-run so the file gets highlighted
        else:
            if terms:  # the filter would hide it: clear it and show the folder tree
                self.query_one("#filter", Input).value = ""
                self.apply_filter("")
            self.reveal_file(path)
        self.action_focus_tree()

    # --- settings ---

    def action_save_location(self) -> None:
        rel_file = None
        if self.current_file:
            try:
                rel_file = self.current_file.relative_to(self.root).as_posix()
            except ValueError:
                pass
        location = {"root": str(self.root), "file": rel_file, "filter": self.filter_text or None}
        if self._write_settings({"location": location}):
            self.settings["location"] = location
            saved = [n for n, v in (("file", rel_file), ("filter", self.filter_text)) if v]
            self.notify(
                f"Saved {' and '.join(saved) or 'folder'} to {self.settings_path.name}",
                timeout=3,
            )

    def watch_theme(self, theme: str) -> None:
        # Persist theme changes (e.g. from the ctrl+p palette) right away.
        ui = self.settings.setdefault("ui", {})
        if ui.get("theme") != theme and self._write_settings({"ui": {"theme": theme}}):
            ui["theme"] = theme

    def _write_settings(self, updates: dict[str, dict[str, Any]]) -> bool:
        try:
            save_settings(self.settings_path, updates)
            return True
        except OSError as exc:
            self.notify(f"Couldn't write {self.settings_path}: {exc}", severity="error")
        except Exception as exc:  # syntax error in a hand-edited file: don't clobber it
            self.notify(
                f"Not saving: {self.settings_path.name} has an error ({exc})",
                severity="error", timeout=8,
            )
        return False

    # --- indexing (runs in a thread so the UI never blocks) ---

    @work(thread=True, exclusive=True)
    def build_index(self) -> None:
        files = scan(self.root, BasePreview.supported_extensions())
        self.call_from_thread(self._index_ready, files)

    def _index_ready(self, files: list[str]) -> None:
        self.index = files
        self._lower_index = [f.lower() for f in files]
        self.query_one("#filter", Input).placeholder = f"Filter {len(files):,} files…"
        self.apply_filter(self.filter_text)  # apply anything typed while indexing

    def action_reindex(self) -> None:
        self.index = None
        self.query_one("#filter", Input).placeholder = "Indexing…"
        self.query_one("#browse", DirectoryTree).reload()
        self.build_index()

    # --- filtering ---

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._filter_timer is not None:
            self._filter_timer.stop()
        self._filter_timer = self.set_timer(0.15, partial(self.apply_filter, event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_focus_tree()  # Enter in the filter box jumps to the results

    def apply_filter(self, text: str) -> None:
        self.filter_text = text
        switcher = self.query_one("#switcher", ContentSwitcher)
        terms = text.lower().split()
        if not terms:
            switcher.current = "browse"
            return
        switcher.current = "results"
        results = self.query_one("#results", Tree)
        results.clear()
        if self.index is None:
            results.root.add_leaf("Indexing… results will appear when it finishes")
            return

        matches = [
            rel for rel, low in zip(self.index, self._lower_index)
            if all(t in low for t in terms)
        ]
        self._populate_results(results, matches[:MAX_RESULTS])
        shown = min(len(matches), MAX_RESULTS)
        results.border_title = (
            f"{len(matches):,} match{'es' if len(matches) != 1 else ''}" if shown == len(matches)
            else f"showing {shown:,} of {len(matches):,}"
        )

    def _populate_results(self, tree: Tree, matches: list[str]) -> None:
        if not matches:
            tree.root.add_leaf("No matches")
            return
        dir_nodes: dict[str, Any] = {"": tree.root}
        current = None
        for rel in matches:
            parent_key = ""
            parts = Path(rel).parts
            for part in parts[:-1]:  # create folder nodes on demand, expanded
                key = os.path.join(parent_key, part)
                if key not in dir_nodes:
                    dir_nodes[key] = dir_nodes[parent_key].add(f"📁 {part}", expand=True)
                parent_key = key
            path = self.root / rel
            leaf = dir_nodes[parent_key].add_leaf(parts[-1], data=path)
            if path == self.current_file:
                current = leaf
        if current is not None:  # keep the open file highlighted across re-filters
            self.call_after_refresh(tree.move_cursor, current)

    # --- preview ---

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.show_preview(event.path)

    @on(Tree.NodeSelected, "#results")
    def result_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, Path):
            self.show_preview(event.node.data)

    def show_preview(self, path: Path) -> None:
        self.current_file = path
        preview = self.query_one("#preview", VerticalScroll)
        preview.remove_children()
        preview.mount(Static(Text(f"Loading {path.name}…", style="dim")))
        self.load_preview(path)

    # Heavy work (reading files, parquet stats) runs off the UI thread.
    # exclusive=True means selecting another file supersedes this one.
    @work(thread=True, exclusive=True, group="preview")
    def load_preview(self, path: Path) -> None:
        widget = BasePreview.for_path(path, self.preview_context).build_safely()
        if not get_current_worker().is_cancelled:
            self.call_from_thread(self._mount_preview, widget)

    async def _mount_preview(self, widget: Widget) -> None:
        preview = self.query_one("#preview", VerticalScroll)
        await preview.remove_children()
        await preview.mount(widget)
        preview.scroll_home(animate=False)

    # --- focus helpers ---

    def action_focus_filter(self) -> None:
        self.query_one("#filter").focus()

    def action_focus_tree(self) -> None:
        self.query_one("#switcher", ContentSwitcher).visible_content.focus()   #type: ignore



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    import argparse

    # DEFAULT_ROOT = Path("data/")
    # DEFAULT_META_KEYS = ["fxt-data:type", "fxt-data:json"]

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])   #type: ignore
    parser.add_argument(
        "root", nargs="?", type=Path,# default=DEFAULT_ROOT,
        help="folder to browse (default: last saved location, else the current dir)",
    )
    parser.add_argument(
        "--meta-key", action="append", metavar="KEY", #default=DEFAULT_META_KEYS,
        help="parquet metadata key to show, exact or glob like 'fxt-data*'; repeat to set "
             "the order (default: [defaults].meta_keys in settings.toml)",
    )
    args = parser.parse_args()
    FileBrowserApp(args.root, metadata_keys=args.meta_key).run()