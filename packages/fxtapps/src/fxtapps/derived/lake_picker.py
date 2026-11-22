#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
"""
Generic Textual picker for yearly lake files: fuzzy search on the left; job
buttons, a live check table and a log on the right. One instance per job type:

    LakePicker(
        root=LAKE.raw(),                  # where to look
        filters={"interval": "TICK"},     # optional extra scan() filters
        action_label="Generate 1MIN bars",
        action=build_1min,                # (ctx: JobContext) -> None
        out_path=out_path_1min,           # optional (key) -> Path; gives ctx.dst + ✓ column
        pre_checks=[...],                 # optional, run BEFORE the action; failures block it
        checks=[...],                     # optional, run AFTER the action
    ).run()

Selection: click / Enter / Space marks files (Ctrl+A marks everything the
search shows, Ctrl+X unmarks all). Run and Verify work through the marked
files one at a time, in lake order; a failed file is recorded and the batch
moves on. Pause stops after the current file; Run then resumes with the marked
files the batch hasn't processed yet. Moving the cursor over a processed file
shows its last check results.

When there's a "done" notion (out_path or is_done), the "hide done" switch
(key: d) drops finished files from the list so only work still to do shows;
Ctrl+A then marks just those. Marked files stay marked while hidden, as with
search. Files finished mid-batch drop out when the batch ends.

`root` must sit inside the lake (raw/ or derived/, optionally deeper); its
hive parts become scan() filters automatically.

Checks come from fxt.core.checks (Check[JobContext]); see that module for how
to write them. This module only runs and displays them:

    Run:    pre_checks -> action -> checks. A failing pre-check skips the action
            unless the "force" switch is on.
    Verify: pre_checks + checks against existing output, no rebuild.

The action can add its own rows with ctx.report(name, result). Each file's
combined CheckReport is kept in `app.reports[path]` (the latest one also on
`app.last_report`) and handed to `on_report`, if given, e.g. to store it in
the output file's meta.
"""

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable

from rapidfuzz import fuzz
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Log, Static, Switch

from fxt.core.checks import (
    BAD_STATUSES, Check, CheckReport, CheckResult, Status,
    flatten_checks, run_checks, skip_checks,
)
from fxt.lake.jobs import JobContext, LogFn
from fxt.lake.paths import PARTITION_KEYS, Lake, LakeType, PartitionKey

Action   = Callable[[JobContext], None]
OnReport = Callable[[JobContext, CheckReport, str], None]   # (ctx, report, outcome)


#!================================================================================(80)
#! display states
#!--------------------------------------------------------------------------------(80)
class Progress(StrEnum):
    """ Where a check is right now. Display-only: results use fxt.core.checks.Status. """
    PENDING = "pending"
    RUNNING = "running"
#

RowState = Status | Progress

STATE_STYLE: dict[RowState, tuple[str, str]] = {   # icon, rich style
    Progress.PENDING: ("○", "dim"),
    Progress.RUNNING: ("…", "yellow"),
    Status.PASS:      ("✓", "green"),
    Status.WARN:      ("!", "yellow"),
    Status.FAIL:      ("✗", "red"),
    Status.ERROR:     ("✗", "bold red"),
    Status.SKIP:      ("-", "dim"),
}

class Outcome(StrEnum):
    PASSED        = "PASSED"
    FAILED        = "FAILED"
    BLOCKED       = "BLOCKED"          # pre-checks failed, action not run
    ACTION_FAILED = "ACTION FAILED"    # action raised
    SKIPPED       = "SKIPPED"          # verify: no output to check (not run, no on_report)
#

OUTCOME_STYLE: dict[Outcome, tuple[str, str]] = {   # short label, rich style
    Outcome.PASSED:        ("✓ passed",  "green"),
    Outcome.FAILED:        ("✗ failed",  "red"),
    Outcome.BLOCKED:       ("⊘ blocked", "red"),
    Outcome.ACTION_FAILED: ("✗ error",   "bold red"),
    Outcome.SKIPPED:       ("- skipped", "dim"),
}

def outcome_text(outcome: Outcome | None) -> Text:
    if outcome is None:
        return Text("")
    label, style = OUTCOME_STYLE[outcome]
    return Text(label, style=style)
#


#!================================================================================(80)
#! lake helpers
#!--------------------------------------------------------------------------------(80)
def scan_args(lake: Lake, root: Path) -> tuple[LakeType, dict[str, str]]:
    """ LAKE.derived(source="dukascopy") -> (DERIVED, {"source": "dukascopy"}) """
    try:
        rel = root.resolve().relative_to(lake.root.resolve())
    except ValueError:
        raise ValueError(f"{root} is not inside the lake ({lake.root})") from None
    if not rel.parts:
        raise ValueError(f"root must be a lake type dir or below it, e.g. {lake.root / 'raw'}")
    laketype = LakeType(rel.parts[0])
    filters = dict(p.split("=", 1) for p in rel.parts[1:] if "=" in p)
    return laketype, filters
#


#!================================================================================(80)
#! search
#!--------------------------------------------------------------------------------(80)
@dataclass(frozen=True)
class Entry:
    key: PartitionKey
    path: Path
    tokens: tuple[str, ...]

    @classmethod
    def make(cls, key: PartitionKey, path: Path) -> "Entry":
        tokens = tuple(str(getattr(key, k)).lower() for k in PARTITION_KEYS)
        return cls(key=key, path=path, tokens=tokens + (path.stem.lower(),))
#

MIN_WORD_SCORE = 70  # a query word scoring below this against every field drops the entry

def _word_score(w: str, t: str) -> float:
    if w in t:                                # substring: "jpy", "eurg", "201"
        return 100.0
    s = fuzz.ratio(w, t)                      # whole-token typo: "eurgpy" ~ "eurgbp"
    if 4 <= len(w) < len(t):                  # typo'd prefix: "eurgb" ~ "eurgbp"
        s = max(s, fuzz.partial_ratio(w, t))  # (short words skip: "jpy" !~ "dukascoPY")
    return s

def score(entry: Entry, query: str) -> float | None:
    """ Mean of each query word's best match over the entry's fields; any word
        under MIN_WORD_SCORE drops the entry. Word order doesn't matter.
    """
    words = query.lower().split()
    if not words:
        return 100.0
    best = []
    for w in words:
        s = max(_word_score(w, t) for t in entry.tokens)
        if s < MIN_WORD_SCORE:
            return None
        best.append(s)
    return sum(best) / len(best)

def search(entries: list[Entry], query: str) -> list[Entry]:
    scored = [(s, e) for e in entries if (s := score(e, query)) is not None]
    scored.sort(key=lambda se: -se[0])        # stable: ties keep scan order
    return [e for _, e in scored]
#


#!================================================================================(80)
#! batch state
#!--------------------------------------------------------------------------------(80)
@dataclass
class Batch:
    """ One Run or Verify over the marked files. Survives Pause, so Resume
        continues with the marked files it hasn't processed yet.
    """
    build:  bool
    force:  bool
    done:   dict[Path, Outcome] = field(default_factory=dict)
    paused: bool = False

    def count(self, *outcomes: Outcome) -> int:
        return sum(1 for o in self.done.values() if o in outcomes)
#


#!================================================================================(80)
#! app
#!--------------------------------------------------------------------------------(80)
class LakePicker(App):
    CSS = """
    #left     { width: 5fr; }
    #sidebar  { width: 4fr; min-width: 52; border-left: tall $panel; padding: 0 1; }
    #selscroll { height: auto; max-height: 12; margin: 1 0; }
    #details  { height: auto; }
    #buttons  { height: auto; }
    #buttons Button { width: 1fr; min-width: 10; }
    #batch    { height: auto; padding: 0 1; margin-top: 1; }
    #forcebar { height: auto; margin-top: 1; }
    #forcebar Label { padding: 1 1; color: $text-muted; }
    #current  { height: auto; padding: 0 1; margin-top: 1; color: $text-muted; }
    #checks   { height: 1fr; }
    #summary  { height: auto; padding: 0 1; }
    #log      { height: 9; margin-top: 1; border: round $panel; }
    #filterbar { height: auto; }
    #filterbar Label { padding: 1 1; color: $text-muted; }
    #count    { width: 1fr; color: $text-muted; padding: 0 1; }
    #filterbar #count { padding: 1 1; }
    """
    BINDINGS = [
        Binding("ctrl+f", "focus_search", "Search"),
        Binding("space", "toggle_mark", "Mark", show=False),   # not while typing, see check_action
        Binding("ctrl+a", "mark_all", "Mark all"),
        Binding("ctrl+x", "unmark_all", "Unmark all"),
        Binding("ctrl+r", "run_selected", "Run"),
        Binding("ctrl+v", "verify_selected", "Verify"),
        Binding("p", "pause", "Pause"),          # ctrl+p is the command palette
        Binding("d", "toggle_hide_done", "Hide done"),
        Binding("escape", "clear", "Clear search"),
        Binding("q", "quit", "Quit"),
    ]
    # keys that mean something else while typing in the search box
    TYPING_KEYS = {"quit", "toggle_mark", "mark_all", "pause", "toggle_hide_done"}

    def __init__(self,
        root: Path,
        action_label: str,
        action: Action,
        *,
        filters:    dict[str, str] | None = None,
        out_path:   Callable[[PartitionKey], Path] | None = None,
        pre_checks: Iterable[Check[JobContext] | Iterable[Check[JobContext]]] = (),
        checks:     Iterable[Check[JobContext] | Iterable[Check[JobContext]]] = (),
        is_done:    Callable[[PartitionKey], bool] | None = None,
        on_report:  OnReport | None = None,
        title:      str | None = None,
        lake:       Lake | None = None,
    ):
        super().__init__()
        if lake is None:
            from fxt.services import get_lake
            lake = get_lake()
        self.lake = lake
        self.root = root
        self.action_label = action_label
        self.action_fn = action
        self.out_path = out_path
        self.on_report = on_report
        self.pre_checks = flatten_checks(pre_checks)
        self.post_checks = flatten_checks(checks)
        flatten_checks(self.all_checks)           # ids must also be unique across both stages
        if is_done is None and out_path is not None:
            is_done = lambda k: out_path(k).exists()
        self.is_done = is_done
        self.hide_done = False                    # list filter: drop files is_done() says are built
        self.title = title or action_label

        laketype, root_filters = scan_args(lake, root)
        for k, v in (filters or {}).items():
            if k in root_filters and root_filters[k] != str(v):
                raise ValueError(f"filter {k}={v} conflicts with root ({k}={root_filters[k]})")
        self.laketype = laketype
        self.filters = {**root_filters, **(filters or {})}

        self.entries: list[Entry] = []
        self.results: list[Entry] = []
        self.marked: dict[Path, Entry] = {}       # the selection, by path (survives searches)
        self.reports: dict[Path, tuple[CheckReport, float, Outcome]] = {}
        self.batch: Batch | None = None
        self.current: Entry | None = None         # file the worker is on right now
        self._queue: list[Entry] = []             # files of the running start/resume
        self.busy = False
        self._pause = threading.Event()
        self.last_report: CheckReport | None = None

    @property
    def all_checks(self) -> list[Check[JobContext]]:
        return self.pre_checks + self.post_checks

    #~======================================================================(70)
    #~ layout
    #~----------------------------------------------------------------------(70)
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield Input(placeholder="e.g.  eurgbp 2014", id="search")
                if self.is_done:
                    with Horizontal(id="filterbar"):
                        yield Static(id="count")
                        yield Switch(value=self.hide_done, id="hidedone")
                        yield Label("hide done")
                else:
                    yield Static(id="count")
                yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
            with Vertical(id="sidebar"):
                with VerticalScroll(id="selscroll"):
                    yield Static(id="details")
                with Horizontal(id="buttons"):
                    yield Button(self.action_label, id="run", variant="primary", disabled=True)
                    if self.all_checks:
                        yield Button("Verify", id="verify", disabled=True)
                    yield Button("Pause", id="pause", variant="warning", disabled=True)
                yield Static(id="batch")
                if self.pre_checks:
                    with Horizontal(id="forcebar"):
                        yield Switch(value=False, id="force")
                        yield Label("force: build even if pre-checks fail")
                if self.all_checks:
                    yield Static(id="current")
                    yield DataTable(id="checks", cursor_type="none", show_cursor=False)
                    yield Static(id="summary")
                yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        f = " ".join(f"{k}={v}" for k, v in self.filters.items())
        self.sub_title = f"{self.laketype}  {f}".strip()
        t = self.query_one("#results", DataTable)
        t.add_column("●", key="mark", width=1)
        for k in PARTITION_KEYS:
            t.add_column(k, key=k)
        t.add_column("file", key="file")
        if self.is_done:
            t.add_column("done", key="done")
        t.add_column("last run", key="outcome")
        if self.all_checks:
            t = self.query_one("#checks", DataTable)
            t.add_column("", key="icon", width=1)
            t.add_column("group", key="group")
            t.add_column("check", key="name")
            t.add_column("s", key="secs")
            t.add_column("detail", key="detail")
            for c in self.all_checks:
                t.add_row("", c.group, c.name, "", "", key=c.id)  # icon, group, name, secs, detail
            self.reset_checks()
        self.rescan()
        self._refresh_selection()
        self._refresh_batch()
        self.query_one(Input).focus()

    #~======================================================================(70)
    #~ data
    #~----------------------------------------------------------------------(70)
    def rescan(self) -> None:
        self.entries = [Entry.make(k, p) for k, p in self.lake.scan(self.laketype, **self.filters)]
        # marked files that vanished from the lake (deleted/renamed) drop out of the selection
        live = {e.path: e for e in self.entries}
        self.marked = {p: live[p] for p in self.marked if p in live}
        self.refresh_results(self.query_one(Input).value)

    def refresh_results(self, query: str) -> None:
        table = self.query_one("#results", DataTable)
        here = self._cursor_entry()
        found = search(self.entries, query)
        # is_done may hit the disk: ask once per matching file, reuse for filter + ✓ column
        done = {e.path for e in found if self.is_done(e.key)} if self.is_done else set()
        if self.hide_done:
            self.results = [e for e in found if e.path not in done]
        else:
            self.results = found
        table.clear()
        for e in self.results:
            row: list[str | Text] = [self._mark_text(e)]
            row += [str(getattr(e.key, k)) for k in PARTITION_KEYS] + [e.path.name]
            if self.is_done:
                row.append("✓" if e.path in done else "")
            row.append(self._outcome_of(e))
            table.add_row(*row, key=str(e.path))
        if here is not None:                      # keep the cursor on the same file
            idx = next((i for i, e in enumerate(self.results) if e.path == here.path), None)
            if idx is not None:
                table.move_cursor(row=idx)
        count = f"{len(self.results)} / {len(self.entries)} files"
        if self.is_done:
            count += f"  ·  {len(done)} done" + (" (hidden)" if self.hide_done and done else "")
        self.query_one("#count", Static).update(count)
        self._update_buttons()

    def _cursor_entry(self) -> Entry | None:
        table = self.query_one("#results", DataTable)
        if not self.results or table.row_count == 0:
            return None
        row = table.cursor_row
        return self.results[row] if 0 <= row < len(self.results) else None

    def _mark_text(self, e: Entry) -> Text:
        return Text("●", style="bold cyan") if e.path in self.marked else Text("")

    def _outcome_of(self, e: Entry) -> Text:
        if self.current is not None and e.path == self.current.path:
            return Text("… running", style="yellow")
        r = self.reports.get(e.path)
        return outcome_text(r[2] if r else None)

    def _update_row(self, e: Entry) -> None:
        """ Refresh one row's mark/done/outcome cells without rebuilding the table. """
        table = self.query_one("#results", DataTable)
        key = str(e.path)
        if key not in table.rows:                 # filtered out by the search
            return
        table.update_cell(key, "mark", self._mark_text(e))
        if self.is_done:
            table.update_cell(key, "done", "✓" if self.is_done(e.key) else "")
        table.update_cell(key, "outcome", self._outcome_of(e), update_width=True)

    #~======================================================================(70)
    #~ search + marking
    #~----------------------------------------------------------------------(70)
    @on(Input.Changed, "#search")
    def _query_changed(self, event: Input.Changed) -> None:
        self.refresh_results(event.value)

    @on(Input.Submitted, "#search")
    def _query_submitted(self) -> None:
        if self.results:
            table = self.query_one("#results", DataTable)
            table.move_cursor(row=0)
            table.focus()

    @on(DataTable.RowSelected, "#results")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        self._toggle(Path(event.row_key.value))   # click / Enter

    @on(DataTable.RowHighlighted, "#results")
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self.busy:                         # while running, the panel follows the worker
            self._show_report_for(Path(event.row_key.value))

    @on(Switch.Changed, "#hidedone")
    def _hide_done_changed(self, event: Switch.Changed) -> None:
        self.hide_done = event.value
        self.refresh_results(self.query_one(Input).value)

    def action_toggle_hide_done(self) -> None:
        if self.is_done:                          # flipping the switch fires Switch.Changed
            sw = self.query_one("#hidedone", Switch)
            sw.value = not sw.value

    def action_toggle_mark(self) -> None:
        e = self._cursor_entry()
        if e is not None:
            self._toggle(e.path)

    def _toggle(self, path: Path) -> None:
        e = next((x for x in self.entries if x.path == path), None)
        if e is None:
            return
        if path in self.marked:
            del self.marked[path]
        else:
            self.marked[path] = e
        self._update_row(e)
        self._selection_changed()

    def action_mark_all(self) -> None:
        """ Mark everything the search shows; if all of it is already marked, unmark it. """
        shown = self.results
        if shown and all(e.path in self.marked for e in shown):
            for e in shown:
                self.marked.pop(e.path, None)
        else:
            for e in shown:
                self.marked[e.path] = e
        for e in shown:
            self._update_row(e)
        self._selection_changed()

    def action_unmark_all(self) -> None:
        changed = list(self.marked.values())
        self.marked.clear()
        for e in changed:
            self._update_row(e)
        if self.batch is not None and self.batch.paused:
            self.batch = None                     # nothing left to resume: start fresh next time
            self.query_one(Log).write_line("paused batch discarded")
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._refresh_selection()
        self._refresh_batch()
        self._update_buttons()

    def marked_in_order(self) -> list[Entry]:
        """ Marked files in lake (scan) order: source, market, symbol, interval, year. """
        return [e for e in self.entries if e.path in self.marked]

    def _remaining(self) -> list[Entry]:
        """ What Run would process: marked files the paused batch hasn't done yet,
            or every marked file when starting fresh.
        """
        todo = self.marked_in_order()
        if self.batch is not None and self.batch.paused:
            todo = [e for e in todo if e.path not in self.batch.done]
        return todo

    #~======================================================================(70)
    #~ sidebar: selection list, batch status, buttons
    #~----------------------------------------------------------------------(70)
    def _refresh_selection(self) -> None:
        details = self.query_one("#details", Static)
        marked = self.marked_in_order()
        if not marked:
            details.update("[b]No files selected[/]\n[dim]click / Enter / Space to mark  ·  "
                           "Ctrl+A marks everything shown[/]")
            return
        names = [e.path.name for e in marked]
        dupes = {n for n in names if names.count(n) > 1}
        lines = [Text(f"{len(marked)} file{'s' if len(marked) != 1 else ''} selected", style="bold")]
        for e in marked:
            name = (str(e.path.relative_to(self.lake.root)) if e.path.name in dupes
                    else e.path.name)
            status = self._outcome_of(e)
            status.pad_right(max(0, 10 - len(status)))
            lines.append(Text.assemble("  ", status, " ", name))
        details.update(Text("\n").join(lines))

    def _refresh_batch(self) -> None:
        w = self.query_one("#batch", Static)
        b = self.batch
        if b is None:
            w.update("")
            return
        kind = "build" if b.build else "verify"
        if self.busy:
            left: int | None = len([e for e in self._queue if e.path not in b.done])
        elif b.paused:
            left = len(self._remaining())
        else:
            left = None
        total = len(b.done) + (left or 0)
        parts = [Text(kind, style="bold"), Text(f" {len(b.done)}/{total}")]
        for outcome, n in ((Outcome.PASSED, b.count(Outcome.PASSED)),
                           (Outcome.FAILED, b.count(Outcome.FAILED, Outcome.ACTION_FAILED)),
                           (Outcome.BLOCKED, b.count(Outcome.BLOCKED)),
                           (Outcome.SKIPPED, b.count(Outcome.SKIPPED))):
            if n or outcome in (Outcome.PASSED, Outcome.FAILED):
                label = outcome.value.lower() if outcome is not Outcome.FAILED else "failed"
                parts.append(Text(f" · {n} {label}", style=OUTCOME_STYLE[outcome][1]))
        if left is not None:
            parts.append(Text(f" · {left} left", style="dim"))
        if self._pause.is_set() and self.busy:
            parts.append(Text(" · pausing after this file", style="yellow"))
        elif b.paused:
            parts.append(Text(" · paused", style="bold yellow"))
        elif not self.busy:
            parts.append(Text(" · finished", style="dim"))
        w.update(Text.assemble(*parts))

    def _update_buttons(self) -> None:
        run = self.query_one("#run", Button)
        paused = self.batch is not None and self.batch.paused
        if paused and self.batch.build:
            run.label = f"Resume ({len(self._remaining())} left)"
        else:
            run.label = self.action_label
        run.disabled = self.busy or not self._remaining() or (paused and not self.batch.build)
        if self.all_checks:
            v = self.query_one("#verify", Button)
            if paused and not self.batch.build:
                v.label = f"Resume verify ({len(self._remaining())} left)"
            else:
                v.label = "Verify"
            v.disabled = not self._can_verify()
        pause = self.query_one("#pause", Button)
        pause.disabled = not self.busy or self._pause.is_set()
        pause.label = "Pausing…" if self._pause.is_set() else "Pause"

    def _verifiable(self, e: Entry) -> bool:
        # post-checks need existing output; pre-checks alone can always run
        return not self.post_checks or self.is_done is None or self.is_done(e.key)

    def _can_verify(self) -> bool:
        if self.busy or not self.all_checks:
            return False
        if self.batch is not None and self.batch.paused and self.batch.build:
            return any(self._verifiable(e) for e in self.marked_in_order())   # starts fresh
        return any(self._verifiable(e) for e in self._remaining())

    #~======================================================================(70)
    #~ check table
    #~----------------------------------------------------------------------(70)
    def reset_checks(self) -> None:
        if not self.all_checks:
            return
        t = self.query_one("#checks", DataTable)
        declared = {c.id for c in self.all_checks}
        for row_key in list(t.rows):              # drop ad-hoc rows from a previous run
            if row_key.value not in declared:
                t.remove_row(row_key)
        for c in self.all_checks:
            self._set_row(c.id, Progress.PENDING)
        self.query_one("#summary", Static).update("")
        self.query_one("#current", Static).update("")

    def _show_report_for(self, path: Path) -> None:
        """ Fill the check panel with a processed file's last results (or clear it). """
        if not self.all_checks:
            return
        self.reset_checks()
        stored = self.reports.get(path)
        if stored is None:
            return
        report, elapsed, outcome = stored
        self.query_one("#current", Static).update(f"last run: {path.name}")
        for cid, res in report.results.items():
            self._set_row(cid, res.status, res)
        self._show_summary(report, elapsed, outcome)

    def _set_row(self, cid: str, state: RowState, result: CheckResult | None = None) -> None:
        t = self.query_one("#checks", DataTable)
        if cid not in t.rows:                     # ad-hoc result reported by the action
            t.add_row("", "", cid, "", "", key=cid)
        icon, style = STATE_STYLE[state]
        bad = state in BAD_STATUSES
        name = str(t.get_cell(cid, "name"))
        detail = result.detail if result else ""
        secs = f"{result.duration:.2f}" if result and result.duration is not None else ""
        t.update_cell(cid, "icon", Text(icon, style=style))
        t.update_cell(cid, "name", Text(name, style=style if bad else ""), update_width=True)
        t.update_cell(cid, "detail", Text(detail, style="dim"), update_width=True)
        t.update_cell(cid, "secs", Text(secs, style="dim"), update_width=True)

    def _show_summary(self, report: CheckReport, elapsed: float, outcome: Outcome) -> None:
        parts = [Text(f"{n} {s}", style=STATE_STYLE[s][1]) for s, n in report.counts().items()]
        style = "bold green" if outcome is Outcome.PASSED else "bold red"
        self.query_one("#summary", Static).update(Text.assemble(
            Text(f"{outcome}  ", style=style),
            *sum(([p, ", "] for p in parts), [])[:-1],
            Text(f"  ·  {elapsed:.1f}s", style="dim")))

    #~======================================================================(70)
    #~ batch control (UI thread)
    #~----------------------------------------------------------------------(70)
    @on(Button.Pressed, "#run")
    def action_run_selected(self) -> None:
        self._start(build=True)

    @on(Button.Pressed, "#verify")
    def action_verify_selected(self) -> None:
        self._start(build=False)

    @on(Button.Pressed, "#pause")
    def action_pause(self) -> None:
        if self.busy and not self._pause.is_set():
            self._pause.set()
            self.query_one(Log).write_line("⏸ pausing after the current file")
            self._update_buttons()
            self._refresh_batch()

    def _start(self, build: bool) -> None:
        if self.busy:
            return
        resume = self.batch is not None and self.batch.paused and self.batch.build == build
        if not resume:                            # new batch (also replaces a paused one of the other kind)
            if not build and not self._can_verify():
                return
            self.batch = Batch(build=build, force=False)
        queue = self._remaining() if resume else self.marked_in_order()
        if not queue:
            return
        self.batch.paused = False
        # read the switch on every start: it may change between pause and resume
        self.batch.force = self.query_one("#force", Switch).value if self.pre_checks else False
        self._pause.clear()
        self._queue = queue
        self.busy = True
        log = self.query_one(Log)
        verb = "resume" if resume else ("build" if build else "verify")
        log.write_line(f"━━ {verb}: {len(queue)} file{'s' if len(queue) != 1 else ''}")
        self._update_buttons()
        self._refresh_batch()
        self._run_batch(queue, build, self.batch.force)

    def _entry_started(self, entry: Entry) -> None:
        self.current = entry
        self.reset_checks()
        if self.all_checks:
            self.query_one("#current", Static).update(f"running: {entry.path.name}")
        self._update_row(entry)
        self._refresh_selection()
        self._refresh_batch()

    def _entry_finished(self, entry: Entry, report: CheckReport, elapsed: float,
                        outcome: Outcome) -> None:
        self.current = None
        self.reports[entry.path] = (report, elapsed, outcome)
        self.last_report = report
        if self.batch is not None:
            self.batch.done[entry.path] = outcome
        if self.all_checks and report.results:
            self._show_summary(report, elapsed, outcome)
        self._update_row(entry)
        self._refresh_selection()
        self._refresh_batch()

    def _batch_finished(self) -> None:
        self.busy = False
        self.current = None
        b = self.batch
        if b is not None:
            b.paused = self._pause.is_set() and any(
                e.path not in b.done for e in self.marked_in_order())
            log = self.query_one(Log)
            if b.paused:
                log.write_line(f"⏸ paused: {len(self._remaining())} left; Run resumes")
            else:
                failed = b.count(Outcome.FAILED, Outcome.ACTION_FAILED, Outcome.BLOCKED)
                log.write_line(f"━━ batch finished: {b.count(Outcome.PASSED)} passed, "
                               f"{failed} not ok, {b.count(Outcome.SKIPPED)} skipped")
        self._pause.clear()
        self.rescan()                             # refreshes ✓ column, marks, buttons
        self._refresh_selection()
        self._refresh_batch()

    #~======================================================================(70)
    #~ jobs (worker thread)
    #~----------------------------------------------------------------------(70)
    @work(thread=True, exclusive=True)
    def _run_batch(self, queue: list[Entry], build: bool, force: bool) -> None:
        ui = self.call_from_thread
        try:
            for entry in queue:
                if self._pause.is_set():
                    break
                ui(self._entry_started, entry)
                report, elapsed, outcome = self._run_one(entry, build, force)
                ui(self._entry_finished, entry, report, elapsed, outcome)
        finally:
            ui(self._batch_finished)

    def _run_one(self, entry: Entry, build: bool, force: bool) -> tuple[CheckReport, float, Outcome]:
        """ One file: pre-checks -> action -> post-checks -> on_report. Never raises. """
        ui = self.call_from_thread
        log = self.query_one(Log)
        write: LogFn = lambda msg: ui(log.write_line, msg)
        on_start  = lambda c: ui(self._set_row, c.id, Progress.RUNNING)
        on_result = lambda c, r: ui(self._set_row, c.id, r.status, r)
        if not self.all_checks:
            on_start = on_result = None           # no check table to update

        t0 = time.perf_counter()
        if not build and not self._verifiable(entry):
            write(f"- skip {entry.path.name}: no output to verify")
            return CheckReport(), 0.0, Outcome.SKIPPED

        adhoc = CheckReport()
        def report(name: str, result: CheckResult) -> None:
            adhoc.results[name] = result
            if self.all_checks:
                ui(self._set_row, name, result.status, result)

        ctx = JobContext(
            key=entry.key, src=entry.path,
            dst=self.out_path(entry.key) if self.out_path else None,
            log=write, report=report,
        )
        write(f"▶ {'build' if build else 'verify'} {entry.path.name}")
        full, outcome = CheckReport(), Outcome.ACTION_FAILED   # if something below blows up
        try:
            # 1) pre-checks: all run, so every problem shows at once
            pre = run_checks(self.pre_checks, ctx, on_start=on_start, on_result=on_result)

            # 2) action
            blocked = build and not pre.ok and not force
            action_ok = True
            if blocked:
                write("✗ pre-checks failed: not building (turn on force to build anyway)")
            elif build:
                if not pre.ok:
                    write("! pre-checks failed: building anyway (force)")
                try:
                    self.action_fn(ctx)
                except Exception as exc:
                    action_ok = False
                    write(f"✗ {type(exc).__name__}: {exc}")

            # 3) post-checks
            if blocked:
                post = skip_checks(self.post_checks, "blocked by pre-checks", on_result=on_result)
            elif not action_ok:
                post = skip_checks(self.post_checks, "action failed", on_result=on_result)
            else:
                post = run_checks(self.post_checks, ctx, on_start=on_start, on_result=on_result)

            full = pre.merge(adhoc).merge(post)
            if blocked:
                outcome = Outcome.BLOCKED
            elif not action_ok:
                outcome = Outcome.ACTION_FAILED
            elif not full.ok:
                outcome = Outcome.FAILED
                write(f"✗ {len(full.failed)} check(s) failed: {', '.join(full.failed)}")
            else:
                outcome = Outcome.PASSED
                write("✓ finished")

            if self.on_report:
                try:
                    self.on_report(ctx, full, outcome)
                except Exception as exc:
                    write(f"✗ on_report: {type(exc).__name__}: {exc}")
        except Exception as exc:              # bug in the job plumbing: report it, don't hang
            write(f"✗ job crashed: {type(exc).__name__}: {exc}")
        finally:
            ctx.close()
        return full, time.perf_counter() - t0, outcome

    #~======================================================================(70)
    #~ misc
    #~----------------------------------------------------------------------(70)
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # while typing a search, "q", "p", space and ctrl+a belong to the Input; returning
        # False lets the key through (and hides the binding in the footer)
        if action in self.TYPING_KEYS and isinstance(self.focused, Input):
            return False
        if action == "toggle_hide_done" and not self.is_done:
            return False                          # no "done" notion: no switch, no binding
        return True

    def on_descendant_focus(self) -> None:
        self.refresh_bindings()               # footer: show/hide bindings as focus moves

    def on_descendant_blur(self) -> None:
        self.refresh_bindings()

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()

    def action_clear(self) -> None:
        self.query_one(Input).value = ""
        self.query_one(Input).focus()
#