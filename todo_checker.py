#!/usr/bin/env python3
from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from textwrap import dedent

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static

ENV_PATH = Path(__file__).resolve().parent / ".env"


def read_dotenv_value(path: Path, key: str) -> Optional[str]:
    if not path.exists():
        return None

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        name, value = line.split("=", 1)
        if name.strip() != key:
            continue

        return value.strip().strip("'\"")

    return None


def load_devlog_dir() -> Path:
    note_filepath = os.environ.get("NOTE_FILEPATH") or read_dotenv_value(
        ENV_PATH, "NOTE_FILEPATH"
    )
    if not note_filepath:
        raise RuntimeError(
            "NOTE_FILEPATH is not set. Add it to .env or export it in the environment."
        )

    devlog_dir = Path(note_filepath).expanduser()
    if devlog_dir.is_absolute():
        return devlog_dir
    return (ENV_PATH.parent / devlog_dir).resolve()


DEVLOG_DIR = load_devlog_dir()

TODO_RE = re.compile(r"^- \[([ x])\] (.+)$")
DUE_RE = re.compile(r"^\s*-\s*Due:\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass
class Todo:
    line_index: int
    checked: bool
    text: str
    due_date: Optional[str] = None
    due_line_index: Optional[int] = None


def current_devlog_file() -> Path:
    return DEVLOG_DIR / datetime.now().strftime("%m_%Y.txt")


def parse_todos(path: Path) -> list[Todo]:
    if not path.exists():
        return []

    lines = path.read_text().splitlines()
    todos: list[Todo] = []
    current: Optional[Todo] = None

    for idx, line in enumerate(lines):
        stripped = line.strip()

        todo_match = TODO_RE.match(stripped)
        if todo_match:
            current = Todo(
                line_index=idx,
                checked=(todo_match.group(1) == "x"),
                text=todo_match.group(2),
            )
            todos.append(current)
            continue

        if current is not None:
            due_match = DUE_RE.match(stripped)
            if due_match:
                current.due_date = due_match.group(1)
                current.due_line_index = idx

    return todos


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def update_todo_checkbox(path: Path, todo: Todo, checked: bool) -> None:
    lines = path.read_text().splitlines()
    lines[todo.line_index] = f"- [{'x' if checked else ' '}] {todo.text}"
    write_lines(path, lines)


def update_todo_due_date(path: Path, todo: Todo, due_date: str) -> None:
    lines = path.read_text().splitlines()
    due_line = f"    - Due: {due_date}"

    if todo.due_line_index is not None and 0 <= todo.due_line_index < len(lines):
        lines[todo.due_line_index] = due_line
    else:
        insert_at = todo.line_index + 1
        lines.insert(insert_at, due_line)

    write_lines(path, lines)


def clear_todo_due_date(path: Path, todo: Todo) -> None:
    if todo.due_line_index is None:
        return

    lines = path.read_text().splitlines()
    if 0 <= todo.due_line_index < len(lines):
        del lines[todo.due_line_index]
        write_lines(path, lines)


class CalendarDay(Static):
    def __init__(self, label: str, day_value: Optional[int], *, id: str | None = None):
        super().__init__(label, id=id)
        self.day_value = day_value

class DatePickerScreen(ModalScreen[Optional[str]]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "move_left", "Left"),
        Binding("right", "move_right", "Right"),
        Binding("up", "move_up", "Up"),
        Binding("down", "move_down", "Down"),
        Binding("[", "prev_month", "Prev Month"),
        Binding("]", "next_month", "Next Month"),
        Binding("enter", "select_focused", "Select"),
        Binding("c", "today", "Today"),
    ]

    CSS = """
    DatePickerScreen {
        align: center middle;
    }

    #calendar-modal {
        width: 44;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 1;
    }

    #calendar-title {
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }

    .weekday-row {
        layout: horizontal;
        height: 1;
        margin-bottom: 1;
    }

    .weekday {
        width: 5;
        content-align: center middle;
        text-style: bold;
    }

    #calendar-grid {
        layout: vertical;
        height: auto;
    }

    .week-row {
        layout: horizontal;
        height: 1;
        margin-bottom: 1;
    }

    .day-cell {
        width: 5;
        content-align: center middle;
    }

    .empty-day {
        width: 5;
    }

    .selected-day {
        background: $accent;
        color: $text;
        text-style: bold;
    }

    #calendar-help {
        margin-top: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, initial_date: Optional[str] = None):
        super().__init__()
        if initial_date:
            try:
                parsed = datetime.strptime(initial_date, "%Y-%m-%d").date()
            except ValueError:
                parsed = date.today()
        else:
            parsed = date.today()

        self.cursor_year = parsed.year
        self.cursor_month = parsed.month
        self.selected_day = parsed.day

    def compose(self) -> ComposeResult:
        with Container(id="calendar-modal"):
            yield Static("", id="calendar-title")
            with Horizontal(classes="weekday-row"):
                for wd in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
                    yield Static(wd, classes="weekday")
            with Vertical(id="calendar-grid"):
                pass
            yield Static(
                "Enter: select  [ / ]: month  arrows: move  c: today  esc: cancel",
                id="calendar-help",
            )

    def on_mount(self) -> None:
        self.render_calendar()

    def render_calendar(self) -> None:
        self.query_one("#calendar-title", Static).update(
            f"{calendar.month_name[self.cursor_month]} {self.cursor_year}"
        )

        grid = self.query_one("#calendar-grid", Vertical)
        grid.remove_children()

        cal = calendar.Calendar(firstweekday=0)
        month_weeks = cal.monthdayscalendar(self.cursor_year, self.cursor_month)

        month_last_day = calendar.monthrange(self.cursor_year, self.cursor_month)[1]
        if self.selected_day > month_last_day:
            self.selected_day = month_last_day

        for week_index, week in enumerate(month_weeks):
            children = []

            for day in week:
                if day == 0:
                    children.append(Static(" ", classes="empty-day"))
                else:
                    cell = CalendarDay(str(day), day, id=f"day-{week_index}-{day}")
                    cell.add_class("day-cell")
                    if day == self.selected_day:
                        cell.add_class("selected-day")
                    children.append(cell)

            row = Horizontal(*children, classes="week-row")
            grid.mount(row)

    def _days_in_month(self) -> int:
        return calendar.monthrange(self.cursor_year, self.cursor_month)[1]

    def _set_selected_day(self, new_day: int) -> None:
        self.selected_day = max(1, min(new_day, self._days_in_month()))
        self.render_calendar()

    def action_move_left(self) -> None:
        if self.selected_day > 1:
            self._set_selected_day(self.selected_day - 1)

    def action_move_right(self) -> None:
        if self.selected_day < self._days_in_month():
            self._set_selected_day(self.selected_day + 1)

    def action_move_up(self) -> None:
        self._set_selected_day(self.selected_day - 7)

    def action_move_down(self) -> None:
        self._set_selected_day(self.selected_day + 7)

    def action_prev_month(self) -> None:
        if self.cursor_month == 1:
            self.cursor_month = 12
            self.cursor_year -= 1
        else:
            self.cursor_month -= 1
        self.render_calendar()

    def action_next_month(self) -> None:
        if self.cursor_month == 12:
            self.cursor_month = 1
            self.cursor_year += 1
        else:
            self.cursor_month += 1
        self.render_calendar()

    def action_today(self) -> None:
        today = date.today()
        self.cursor_year = today.year
        self.cursor_month = today.month
        self.selected_day = today.day
        self.render_calendar()

    def action_select_focused(self) -> None:
        selected = date(self.cursor_year, self.cursor_month, self.selected_day)
        self.dismiss(selected.isoformat())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self, event) -> None:
        if isinstance(event.widget, CalendarDay) and event.widget.day_value is not None:
            self.selected_day = event.widget.day_value
            selected = date(self.cursor_year, self.cursor_month, self.selected_day)
            self.dismiss(selected.isoformat())

class TodoRow(ListItem):
    def __init__(self, todo: Todo):
        self.todo = todo
        self.todo_label = Static("", classes="todo-text")
        self.due_label = Static("", classes="due-label")
        self.inner = Horizontal(
            self.todo_label,
            self.due_label,
            classes="todo-row-inner",
        )
        super().__init__(self.inner)
        self.refresh_row()

    def render_todo_text(self) -> str:
        box = "☑" if self.todo.checked else "☐"
        if self.todo.checked:
            return f"{box} [strike]{self.todo.text}[/strike]"
        return f"{box} {self.todo.text}"

    def render_due_text(self) -> str:
        return self.todo.due_date if self.todo.due_date else "Set due"

    def refresh_row(self) -> None:
        self.todo_label.update(self.render_todo_text())
        self.due_label.update(self.render_due_text())

        self.due_label.remove_class("has-due")
        self.due_label.remove_class("no-due")

        if self.todo.due_date:
            self.due_label.add_class("has-due")
        else:
            self.due_label.add_class("no-due")


class Ticker(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    ListView {
        height: 1fr;
        border: round $panel;
    }

    ListItem {
        height: auto;
    }
    
	#ascii-art {
        content-align: center middle;
		color: $text-muted;
		margin-bottom: 1;
	}

    .todo-row-inner {
        layout: horizontal;
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    .todo-text {
        width: 1fr;
        content-align: left middle;
    }

    .due-label {
        width: 16;
        min-width: 16;
        height: 1;
        content-align: center middle;
    }

    .has-due {
        color: $text;
        text-style: bold;
    }

    .no-due {
        color: $text-muted;
    }
    """

    ASCII_ART = dedent(r'''
                       _.-**-._           ____________
                    _,(        ),_       /            \
                 .-"   '-^----'   "-.   |  TO DO List |
              .-'                    '-.  \____________/
            .'                          '.
          .'    __.--**'""""""'**--.__    '.
         /_.-*"'__.--**'""""""'**--.__'"*-._\
        /_..-*"'   .-*"*-.  .-*"*-.   '"*-.._\
       :          /       ;:       \          ;
       :         :     *  !!  *     :         ;
        \        '.     .'  '.     .'        /
         \         '-.-'      '-.-'         /
      .-*''.                              .'-.
   .-'      '.                          .'    '.
  :           '-.        _.._        .-'        '._
 ;"*-._          '-._  --___ `   _.-'        _.*'  '*.
:      '.            `"*-.__.-*"`           (        :
 ;      ;                 *|                 '-.     ;
  '---*'                   |                    ""--'
   :                      *|                      :
   '.                      |                     .'
     '.._                 *|        ____----.._-'
      \  """----_____------'-----"""         /
       \  __..-------.._        ___..---._  /
       :'"              '-..--''          "';
        '""""""""""""""""' '"""""""""""""""'
    ''').strip("\n")

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "toggle", "Toggle"),
        Binding("r", "reload", "Reload"),
        Binding("d", "edit_due_date", "Due Date"),
        Binding("x", "clear_due_date", "Clear Due"),
    ]

    def __init__(self):
        super().__init__()
        self.path = current_devlog_file()
        self.rows: list[TodoRow] = []

    def compose(self) -> ComposeResult:
        yield Static(self.ASCII_ART, id="ascii-art")
        yield ListView()
        yield Footer()

    def on_mount(self) -> None:
        self.reload_rows()

    def get_selected_row(self) -> Optional[TodoRow]:
        lv = self.query_one(ListView)
        if lv.index is None:
            return None
        if lv.index < 0 or lv.index >= len(self.rows):
            return None
        return self.rows[lv.index]

    def reload_rows(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

        lv = self.query_one(ListView)
        lv.clear()
        self.rows = []

        todos = parse_todos(self.path)
        for todo in todos:
            row = TodoRow(todo)
            self.rows.append(row)
            lv.append(row)

    def action_reload(self) -> None:
        self.path = current_devlog_file()
        self.reload_rows()

    def action_toggle(self) -> None:
        row = self.get_selected_row()
        if row is None:
            return

        row.todo.checked = not row.todo.checked
        update_todo_checkbox(self.path, row.todo, row.todo.checked)
        self.reload_rows()

    def action_edit_due_date(self) -> None:
        row = self.get_selected_row()
        if row is None:
            return

        self.push_screen(
            DatePickerScreen(initial_date=row.todo.due_date),
            callback=lambda selected, current_row=row: self._handle_due_date_selected(current_row, selected),
        )

    def _handle_due_date_selected(self, row: TodoRow, selected: Optional[str]) -> None:
        if not selected:
            return

        update_todo_due_date(self.path, row.todo, selected)
        self.reload_rows()

    def action_clear_due_date(self) -> None:
        row = self.get_selected_row()
        if row is None:
            return

        clear_todo_due_date(self.path, row.todo)
        self.reload_rows()

    def on_click(self, event: Click) -> None:
        for idx, row in enumerate(self.rows):
            if event.widget is row.due_label:
                lv = self.query_one(ListView)
                lv.index = idx
                self.push_screen(
                    DatePickerScreen(initial_date=row.todo.due_date),
                    callback=lambda selected, current_row=row: self._handle_due_date_selected(current_row, selected),
                )
                break


if __name__ == "__main__":
    Ticker().run()
