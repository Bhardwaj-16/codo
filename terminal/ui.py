import curses
import locale
import os
import signal
import sys
import time
import threading
import textwrap
import random
import psutil
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Tuple, Optional

H = "─"
V = "│"
TL = "┌"
TR = "┐"
BL = "└"
BR = "┘"
LT = "├"
RT = "┤"
TT = "┬"
BT = "┴"
DBL = "═"
DTL = "╔"
DTR = "╗"
DBL2 = "╚"
DBR = "╝"
BLOCK = "█"
HALF = "░"
DOT = "●"

CP_ORANGE = 1
CP_WHITE = 2
CP_GREEN = 3
CP_RED = 4
CP_CYAN = 5
CP_YELLOW = 6
CP_DIM = 7
CP_HDR = 8
CP_ORANGE2 = 9
CP_SELECTED = 10

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_ERROR = "error"

class CodoUI:
    def __init__(
        self,
        stdscr,
        ai_callback: Callable[[str], str],
        root_dir: str = ".",
        project_name: str = "ROOT_DIR",
    ):
        self.stdscr = stdscr
        self.ai_callback = ai_callback
        self.root_dir = Path(root_dir).resolve()
        self.project_name = project_name

        self.messages: List[Tuple[str, str]] = []
        self.input_buffer = ""
        self.cursor_pos = 0
        self.chat_scroll = 0
        self.file_scroll = 0
        self.selected_file: Optional[Path] = None
        self.thinking = False
        self.think_frame = 0
        self.running = True
        self.agent_state = "AWAITING_INPUT"
        self.session_start = datetime.now()
        self._history: List[str] = []
        self._hist_idx = -1
        self.expanded_paths = set()
        self.focused_panel = "chat"

        self.metrics = {
            "cpu": [0.25, 0.40, 0.55, 0.35, 0.65, 0.50, 0.45],
            "mem_used": 0.0,
            "mem_total": 8.0,
            "tokens": 0,
            "net": {
                "API_GATEWAY": 24,
                "DB_READ": 8,
                "LLM_INFERENCE": 56,
            },
        }
        self._metric_lock = threading.Lock()
        self._start_metrics_thread()

        self.file_tree: List[Tuple[int, str, bool, Path]] = []
        self._refresh_tree()

        self._resize_pending = False

        self.h = self.w = 0
        self.left_w = self.right_w = self.center_w = 0
        self._compute_layout()

        self._init_curses()

        signal.signal(signal.SIGWINCH, self._on_sigwinch)

        self._lwin = None
        self._cwin = None
        self._rwin = None
        self._create_panels()

    def _create_panels(self):
        h, w = self.h, self.w
        HEADER_H = 3
        INPUT_H = 3
        panel_y  = HEADER_H
        panel_h  = max(1, h - HEADER_H - INPUT_H)
        lw = self.left_w
        rw = self.right_w
        cw = max(1, w - lw - rw)
        try:
            self._lwin = curses.newwin(panel_h, lw, panel_y, 0)
            self._cwin = curses.newwin(panel_h, cw, panel_y, lw)
            self._rwin = curses.newwin(panel_h, rw, panel_y, lw + cw)
        
        except curses.error:
            pass


    def _init_curses(self):
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        self.stdscr.timeout(12)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        self._setup_colors()

    def _setup_colors(self):
        curses.start_color()
        curses.use_default_colors()

        can_custom = curses.can_change_color() and curses.COLORS >= 256

        if can_custom:
            curses.init_color(16, 1000, 430, 0)
            curses.init_color(17, 180, 75, 0)
            curses.init_color(18, 450, 450, 450)
            curses.init_color(19, 900, 700, 200)
            OG = 16
            DK = 17
            DM = 18
            AM = 19

        else:
            OG = curses.COLOR_YELLOW
            DK = curses.COLOR_BLACK
            DM = curses.COLOR_WHITE
            AM = curses.COLOR_YELLOW

        curses.init_pair(CP_ORANGE, OG, -1)
        curses.init_pair(CP_WHITE,curses.COLOR_WHITE, -1)
        curses.init_pair(CP_GREEN,curses.COLOR_GREEN, -1)
        curses.init_pair(CP_RED, curses.COLOR_RED,-1)
        curses.init_pair(CP_CYAN, curses.COLOR_CYAN, -1)
        curses.init_pair(CP_YELLOW, curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_DIM, DM, -1)
        curses.init_pair(CP_HDR, curses.COLOR_BLACK, OG)
        curses.init_pair(CP_ORANGE2, AM, -1)
        curses.init_pair(CP_SELECTED, curses.COLOR_BLACK, OG)

    def _on_sigwinch(self, signum, frame):
        self._resize_pending = True

    def _compute_layout(self):
        try:
            ts = os.get_terminal_size()
            self.h = ts.lines
            self.w = ts.columns
            curses.resizeterm(self.h, self.w)
        except OSError:
            curses.update_lines_cols()
            self.h, self.w = self.stdscr.getmaxyx()
        self.left_w = max(18, min(26, self.w // 6))
        self.right_w = max(24, min(34, self.w // 4))
        self.center_w = self.w - self.left_w - self.right_w

    def _refresh_tree(self):
        self.file_tree = self._build_tree(self.root_dir)

    def _build_tree(self, path: Path, depth = 0, max_depth = 4) -> List[Tuple[int, str, bool, Path]]:
        items = []
        if depth >= max_depth:
            return items
        try:
            entries = sorted(
                path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
            skip = {"__pycache__", ".git", "node_modules", ".DS_Store"}
            for entry in entries:
                if entry.name in skip:
                    continue
                items.append((depth, entry.name, entry.is_dir(), entry))
                if entry.is_dir() and entry in getattr(self, "expanded_paths", set()):
                    items.extend(self._build_tree(entry, depth + 1, max_depth))
        except PermissionError:
            pass
        return items

    def _start_metrics_thread(self):
        def _loop():
            psutil.cpu_percent(interval = 0.1)

            while self.running:
                time.sleep(1.2)
                with self._metric_lock:
                    cpu_pct = psutil.cpu_percent(interval = None) / 100.0
                    
                    cpu = self.metrics["cpu"]
                    cpu.append(max(0.01, min(1.0, cpu_pct)))
                    self.metrics["cpu"] = cpu[-7:]
                    
                    vmem = psutil.virtual_memory()
                    self.metrics["mem_used"] = vmem.used / (1024 ** 3)
                    self.metrics["mem_total"] = vmem.total / (1024 ** 3)

                    for k in self.metrics["net"]:
                        self.metrics["net"][k] = max(
                            1,
                            self.metrics["net"][k] + random.randint(-8, 8),
                        )

        threading.Thread(target=_loop, daemon=True).start()

    @staticmethod
    def _safestr(win, y: int, x: int, text: str, attr: int = 0):
        try:
            max_y, max_x = win.getmaxyx()
            if y < 0 or y >= max_y or x >= max_x - 1:
                return
            if x < 0:
                text = text[-x:]
                x = 0
            avail = max_x - x - 1
            if avail <= 0:
                return
            win.addstr(y, x, text[:avail], attr)
        except curses.error:
            pass

    def _draw_border(self, win, title: str = "", title_attr: int = 0):
        h, w = win.getmaxyx()
        ca = curses.color_pair(CP_ORANGE)
        
        self._safestr(win, 0, 0, TL + H * (w - 2) + TR, ca)
        self._safestr(win, h - 1, 0, BL + H * (w - 2) + BR, ca)
        
        for y in range(1, h - 1):
            self._safestr(win, y, 0, V, ca)
            self._safestr(win, y, w - 1, V, ca)

        if title:
            s = f" {title} "
            tx = max(2, (w - len(s)) // 2)
            self._safestr(win, 0, tx, s, title_attr or (curses.color_pair(CP_ORANGE) | curses.A_BOLD))

    def _hbar(self, win, y: int, x: int, w: int, frac: float, color_pair: int):
        filled = max(0, min(w, int(frac * w)))
        bar = BLOCK * filled + HALF * (w - filled)
        self._safestr(win, y, x, bar, curses.color_pair(color_pair))

    def draw_header(self):
        w = self.w
        self._safestr(self.stdscr, 0, 0, " " * (w - 1), curses.color_pair(CP_HDR))

        logo = " ORIGIN AI "
        self._safestr(self.stdscr, 0, 0, logo, curses.color_pair(CP_HDR) | curses.A_BOLD)

        ver = " v1.0.0 "
        self._safestr(self.stdscr, 0, len(logo), ver, curses.color_pair(CP_ORANGE) | curses.A_BOLD)

        tty = "  ◈ TTY1 - ACTIVE SESSION  "
        self._safestr(self.stdscr, 0, len(logo) + len(ver) + 2, tty, curses.color_pair(CP_WHITE) | curses.A_BOLD)

        if self.agent_state == "AWAITING_INPUT":
            state_attr = curses.color_pair(CP_GREEN) | curses.A_BOLD
        elif self.agent_state == "PROCESSING":
            state_attr = curses.color_pair(CP_YELLOW) | curses.A_BOLD
        else:
            state_attr = curses.color_pair(CP_RED) | curses.A_BOLD

        state_str = f" AGENT_STATE: {self.agent_state} "
        sx = max(len(logo) + len(ver) + len(tty) + 4, w - len(state_str) - 22)
        self._safestr(self.stdscr, 0, sx, state_str, state_attr)

        tele = " TELEMETRY_DATALINK "
        self._safestr(self.stdscr, 0, w - len(tele) - 1, tele, curses.color_pair(CP_HDR) | curses.A_BOLD)

        ts = datetime.now().strftime("%H:%M:%S")
        dt = datetime.now().strftime("%Y-%m-%d")
        up = str(datetime.now() - self.session_start).split(".")[0]
        msgs = len([m for m in self.messages if m[0] == ROLE_USER])
        
        self._safestr(self.stdscr, 1, 0, " " * (w - 1))

        self._safestr(self.stdscr, 1, 1, f"▸ {self.project_name}", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
        self._safestr(self.stdscr, 1, self.left_w + 2, f"DATE:{dt}  TIME:{ts}  UP:{up}  MSGS:{msgs}", curses.color_pair(CP_DIM))

        self._safestr(self.stdscr, 2, 0, H * (w - 1), curses.color_pair(CP_ORANGE))

    def draw_left_panel(self, win):
        h, w = win.getmaxyx()
        inner_h = h - 2

        self._draw_border(win, "EXPLORER")

        self._safestr(win, 1, 1, (f"▾ {self.project_name}")[:w - 2], curses.color_pair(CP_ORANGE) | curses.A_BOLD)

        visible_n = inner_h - 2
        slice_ = self.file_tree[self.file_scroll: self.file_scroll + visible_n]

        y = 2
        for depth, name, is_dir, fpath in slice_:
            if y >= h - 1:
                break
            pad = "  " * depth
            if is_dir:
                prefix = "▾" if fpath in getattr(self, "expanded_paths", set()) else "▸"
                label = f"{pad}{prefix} {name}/"
                attr = curses.color_pair(CP_ORANGE)
            else:
                ext = fpath.suffix.lower()
                if ext in (".py", ".ts", ".tsx", ".js", ".jsx"):
                    attr = curses.color_pair(CP_CYAN)
                elif ext in (".json", ".yaml", ".yml", ".toml", ".env", ".cfg"):
                    attr = curses.color_pair(CP_YELLOW)
                elif ext in (".md", ".txt", ".rst"):
                    attr = curses.color_pair(CP_WHITE)
                else:
                    attr = curses.color_pair(CP_DIM)
                label = f"{pad}  {name}"

            if fpath == self.selected_file:
                attr = curses.color_pair(CP_SELECTED) | curses.A_BOLD
                label = f"{label:<{w - 2}}"

            self._safestr(win, y, 1, label[:w - 2], attr)
            y += 1

        total = len(self.file_tree)
        if total > visible_n and visible_n > 0:
            frac = self.file_scroll / max(1, total - visible_n)
            thumb_y = 2 + int(frac * (visible_n - 1))
            try:
                win.addch(min(thumb_y, h - 2), w - 1, ord("▐"), curses.color_pair(CP_ORANGE))
            except curses.error:
                pass

        self._safestr(win, h - 1, 1, f" {total} items "[:w - 2], curses.color_pair(CP_HDR))

    def draw_center_panel(self, win):
        h, w = win.getmaxyx()
        inner_h = h - 2
        inner_w = w - 2

        title = "CHAT_TERMINAL"
        if self.thinking:
            frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            f = frames[self.think_frame % len(frames)]
            title = f"CHAT_TERMINAL  {f} PROCESSING"
        self._draw_border(win, title)

        rendered: List[Tuple[str, str]] = []
        PS1 = "origin@ai:~$ "

        for role, content in self.messages:
            if role == ROLE_USER:
                rendered.append(("prompt_ps1", PS1))
                rendered.append(("prompt_cmd", content))
            elif role == ROLE_ASSISTANT:
                prefix = "  "
                for line in (textwrap.wrap(content, inner_w - len(prefix) - 1) or [""]):
                    rendered.append(("assistant", f"{prefix}{line}"))
                rendered.append(("blank", ""))
            elif role == ROLE_SYSTEM:
                rendered.append(("system", f"  ◈ {content}"))
                rendered.append(("blank", ""))
            elif role == ROLE_ERROR:
                rendered.append(("error", f"  ✗ {content}"))
                rendered.append(("blank", ""))

        if self.thinking:
            frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            f = frames[self.think_frame % len(frames)]
            rendered.append(("thinking", f"  {f}  Processing request..."))
        total = len(rendered)
        start = max(0, total - inner_h - self.chat_scroll)
        visible = rendered[start: start + inner_h]

        y = 1
        i = 0
        while i < len(visible) and y < h - 1:
            lt, text = visible[i]

            if lt == "prompt_ps1":
                cmd = visible[i + 1][1] if i + 1 < len(visible) else ""
                i += 1
                self._safestr(win, y, 1, PS1, curses.color_pair(CP_GREEN) | curses.A_BOLD)
                self._safestr(win, y, 1 + len(PS1), cmd[:inner_w - len(PS1) - 1], curses.color_pair(CP_WHITE) | curses.A_BOLD)

            elif lt == "assistant":
                self._safestr(win, y, 1, text[:inner_w], curses.color_pair(CP_WHITE))

            elif lt == "system":
                self._safestr(win, y, 1, text[:inner_w], curses.color_pair(CP_CYAN))

            elif lt == "error":
                self._safestr(win, y, 1, text[:inner_w], curses.color_pair(CP_RED) | curses.A_BOLD)

            elif lt == "thinking":
                self._safestr(win, y, 1, text[:inner_w], curses.color_pair(CP_YELLOW) | curses.A_BOLD)

            elif lt == "blank":
                pass

            y += 1
            i += 1

        if total > inner_h:
            frac = max(0.0, min(1.0, (total - inner_h - self.chat_scroll) / max(1, total - inner_h)))
            bar_y = 1 + int(frac * (inner_h - 1))
            try:
                win.addch(min(bar_y, h - 2), w - 1, ord(BLOCK), curses.color_pair(CP_ORANGE))
            except curses.error:
                pass

    def draw_right_panel(self, win):
        h, w = win.getmaxyx()
        inner_w = w - 2
        self._draw_border(win, "SYS_METRICS")

        y = 1

        with self._metric_lock:
            cpu = list(self.metrics["cpu"])
            mem_used = self.metrics["mem_used"]
            mem_total = self.metrics["mem_total"]
            tokens = self.metrics["tokens"]
            net = dict(self.metrics["net"])

        if y < h - 1:
            self._safestr(win, y, 1, "SYS_CPU_LOAD", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
            avg = sum(cpu) / len(cpu)
            pct_str = f"{avg * 100:4.0f}%"
            self._safestr(win, y, inner_w - len(pct_str), pct_str, curses.color_pair(CP_ORANGE))
            y += 1

        if y < h - 1:
            BARS = " ▁▂▃▄▅▆▇█"
            col_w = max(1, (inner_w - 1) // len(cpu))
            x = 1
            for v in cpu:
                idx = min(8, int(v * 9))
                ch = BARS[idx]
                if v > 0.75:
                    ca = curses.color_pair(CP_RED)
                elif v > 0.50:
                    ca = curses.color_pair(CP_ORANGE)
                else:
                    ca = curses.color_pair(CP_GREEN)
                self._safestr(win, y, x, ch * col_w, ca | curses.A_BOLD)
                x += col_w
            y += 1

        if y < h - 1:
            self._hbar(win, y, 1, inner_w - 1, avg, CP_GREEN if avg < 0.5 else CP_YELLOW if avg < 0.75 else CP_RED)
            y += 2

        if y < h - 1:
            self._safestr(win, y, 1, "MEM_ALLOCTION", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
            mem_str = f"{mem_used:.1f} GB"
            self._safestr(win, y, inner_w - len(mem_str), mem_str, curses.color_pair(CP_CYAN) | curses.A_BOLD)
            y += 1

        if y < h - 1:
            self._hbar(win, y, 1, inner_w - 1, mem_used / mem_total, CP_CYAN)
            y += 1

        if y < h - 1:
            used_s = f"USED:{mem_used:.1f}G"
            total_s = f"TOTAL:{mem_total:.0f}G"
            self._safestr(win, y, 1, used_s, curses.color_pair(CP_DIM))
            self._safestr(win, y, inner_w - len(total_s), total_s, curses.color_pair(CP_DIM))
            y += 2

    def draw_input_bar(self):
        h, w = self.h, self.w
        iy = h - 3

        for y in range(iy, h):
            self._safestr(self.stdscr, y, 0, " " * (w - 1))

        self._safestr(self.stdscr, iy, 0, H * (w - 1), curses.color_pair(CP_ORANGE))

        PS1 = "origin@ai:~$ "
        self._safestr(self.stdscr, iy + 1, 0, PS1,curses.color_pair(CP_GREEN) | curses.A_BOLD)
        px = len(PS1)

        buf = self.input_buffer
        cur = self.cursor_pos
        max_w = w - px - 3
        offset = max(0, cur - max_w + 1)
        buf_vis = buf[offset:]
        cur_vis = cur - offset

        self._safestr(self.stdscr, iy + 1, px, buf_vis[:max_w], curses.color_pair(CP_WHITE))

        ch_under = buf_vis[cur_vis] if cur_vis < len(buf_vis) else " "
        try:
            self.stdscr.addstr(
                iy + 1, px + cur_vis, ch_under,
                curses.color_pair(CP_ORANGE) | curses.A_REVERSE,
            )
        except curses.error:
            pass

        if self.thinking:
            hints = " AI PROCESSING — please wait..."
            hattr = curses.color_pair(CP_YELLOW) | curses.A_BOLD
        elif self.focused_panel == "files":
            hints = "  [TAB] → Chat  [↑↓] File Scroll  [PgUp/PgDn] Fast Scroll  [^C] Quit"
            hattr = curses.color_pair(CP_ORANGE) | curses.A_BOLD
        else:
            hints = "  [ENTER] Send  [TAB] → Files  [↑↓] Chat Scroll  [^C] Quit"
            hattr = curses.color_pair(CP_DIM)
        self._safestr(self.stdscr, iy + 2, 0, hints[:w - 1], hattr)

        ts = datetime.now().strftime("%H:%M:%S")
        self._safestr(self.stdscr, iy + 2, w - 12, f"[ {ts} ]", curses.color_pair(CP_ORANGE))

    def draw(self):
        old_h, old_w = self.h, self.w

        if self._resize_pending:
            self._resize_pending = False

        self._compute_layout()
        h, w = self.h, self.w

        if h != old_h or w != old_w or self._lwin is None:
            self.stdscr.clear()
            self.stdscr.refresh()
            self._create_panels()

        if h < 12 or w < 70:
            self.stdscr.erase()
            msg = " Terminal too small — please resize "
            self._safestr(self.stdscr, h // 2, max(0, (w - len(msg)) // 2), msg, curses.color_pair(CP_RED) | curses.A_BOLD)
            self.stdscr.noutrefresh()
            curses.doupdate()
            return

        if not self._lwin or not self._cwin or not self._rwin:
            return

        self.draw_header()
        self.stdscr.noutrefresh()

        self._lwin.erase()
        self.draw_left_panel(self._lwin)
        self._lwin.noutrefresh()

        self._cwin.erase()
        self.draw_center_panel(self._cwin)
        self._cwin.noutrefresh()

        self._rwin.erase()
        self.draw_right_panel(self._rwin)
        self._rwin.noutrefresh()

        self.draw_input_bar()
        self.stdscr.noutrefresh()

        curses.doupdate()

    def _rendered_line_count(self) -> int:
        inner_w = max(20, self.center_w - 4)
        n = 0
        for role, content in self.messages:
            if role in (ROLE_USER, ROLE_SYSTEM, ROLE_ERROR):
                n += 2
            else:
                n += len(textwrap.wrap(content, inner_w) or [""]) + 1
        return n

    def handle_key(self, key: int):
        if key == ord("\t"):
            self.focused_panel = "files" if self.focused_panel == "chat" else "chat"
            return

        if key == curses.KEY_PPAGE:
            self.file_scroll = max(0, self.file_scroll - 10)
            return
        if key == curses.KEY_NPAGE:
            max_fs = max(0, len(self.file_tree) - 1)
            self.file_scroll = min(self.file_scroll + 10, max_fs)
            return

        if key == curses.KEY_UP:
            if self.focused_panel == "files":
                self.file_scroll = max(0, self.file_scroll - 1)
            else:
                max_scroll = max(0, self._rendered_line_count() - (self.h - 8))
                self.chat_scroll = min(self.chat_scroll + 1, max_scroll)
            return
        if key == curses.KEY_DOWN:
            if self.focused_panel == "files":
                max_fs = max(0, len(self.file_tree) - 1)
                self.file_scroll = min(self.file_scroll + 1, max_fs)
            else:
                self.chat_scroll = max(0, self.chat_scroll - 1)
            return

        if key == curses.KEY_LEFT:
            self.cursor_pos = max(0, self.cursor_pos - 1); return
        if key == curses.KEY_RIGHT:
            self.cursor_pos = min(len(self.input_buffer), self.cursor_pos + 1); return
        if key == curses.KEY_HOME or key == 1:
            self.cursor_pos = 0; return
        if key == curses.KEY_END or key == 5:
            self.cursor_pos = len(self.input_buffer); return

        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor_pos > 0:
                buf = self.input_buffer
                self.input_buffer = buf[:self.cursor_pos - 1] + buf[self.cursor_pos:]
                self.cursor_pos -= 1
            return
        if key == curses.KEY_DC:
            buf = self.input_buffer
            if self.cursor_pos < len(buf):
                self.input_buffer = buf[:self.cursor_pos] + buf[self.cursor_pos + 1:]
            return

        if key in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            self._submit()
            return

        if key == curses.KEY_RESIZE:
            self._resize_pending = True
            self.h = 0
            return

        if 32 <= key <= 126:
            ch = chr(key)
            self.input_buffer = (
                self.input_buffer[:self.cursor_pos]
                + ch
                + self.input_buffer[self.cursor_pos:]
            )
            self.cursor_pos += 1

    def handle_mouse(self, event):
        try:
            _, mx, my, _, bstate = event
        except Exception:
            return

        HEADER_H = 3
        INPUT_H  = 3
        panel_y  = HEADER_H
        panel_h  = self.h - HEADER_H - INPUT_H
        lw = self.left_w
        rw = self.right_w
        cw = self.center_w

        in_panel = panel_y <= my < panel_y + panel_h
        SCROLL_UP_MASK = getattr(curses, 'BUTTON4_PRESSED', 0) or (1 << 21)
        SCROLL_DOWN_MASK = getattr(curses, 'BUTTON5_PRESSED', 0) or (1 << 27)
        is_scroll_up = bool(bstate & SCROLL_UP_MASK)
        is_scroll_down = bool(bstate & SCROLL_DOWN_MASK)

        if in_panel and 0 <= mx < lw:
            if is_scroll_up:
                self.file_scroll = max(0, self.file_scroll - 1)
            elif is_scroll_down:
                self.file_scroll = min(
                    max(0, len(self.file_tree) - 1),
                    self.file_scroll + 1,
                )
            elif getattr(curses, 'BUTTON1_CLICKED', 0) and (bstate & curses.BUTTON1_CLICKED):
                row = my - panel_y - 2
                idx = row + self.file_scroll
                if 0 <= idx < len(self.file_tree):
                    depth, name, is_dir, fpath = self.file_tree[idx]
                    self.selected_file = fpath
                    if is_dir:
                        if not hasattr(self, "expanded_paths"):
                            self.expanded_paths = set()
                        if fpath in self.expanded_paths:
                            self.expanded_paths.remove(fpath)
                        else:
                            self.expanded_paths.add(fpath)
                        self._refresh_tree()
                    else:
                        self.input_buffer = str(fpath)
                        self.cursor_pos = len(self.input_buffer)

        if in_panel and lw <= mx < lw + cw:
            if is_scroll_up:
                max_s = max(0, self._rendered_line_count() - (panel_h - 2))
                self.chat_scroll = min(self.chat_scroll + 3, max_s)
            elif is_scroll_down:
                self.chat_scroll = max(0, self.chat_scroll - 3)

    def _submit(self):
        text = self.input_buffer.strip()
        if not text or self.thinking:
            return

        self.input_buffer = ""
        self.cursor_pos = 0
        self.chat_scroll = 0
        self._history.append(text)
        self._hist_idx = -1

        self.messages.append((ROLE_USER, text))
        self.thinking = True
        self.agent_state = "PROCESSING"

        def _run():
            try:
                with self._metric_lock:
                    self.metrics["tokens"] += len(text.split())
                response = self.ai_callback(text)
                with self._metric_lock:
                    self.metrics["tokens"] += len(response.split())
                self.messages.append((ROLE_ASSISTANT, response))
            except Exception as exc:
                self.messages.append((ROLE_ERROR, str(exc)))
            finally:
                self.thinking = False
                self.agent_state = "AWAITING_INPUT"

        threading.Thread(target=_run, daemon=True).start()

    def run(self):
        self.messages.append((
            ROLE_SYSTEM,
            "ORIGIN AI initialized. Type a message...",
        ))

        FPS = 30
        frame_dur = 1.0 / FPS
        last_draw = 0.0

        while self.running:
            now = time.monotonic()
            if now - last_draw >= frame_dur:
                if self.thinking:
                    self.think_frame += 1
                self.draw()
                last_draw = now

            try:
                key = self.stdscr.getch()
            except curses.error:
                key = -1

            if key == -1:
                time.sleep(0.008)
                continue

            if key == 3:
                self.running = False
                break

            if key == curses.KEY_MOUSE:
                try:
                    self.handle_mouse(curses.getmouse())
                except curses.error:
                    pass
                continue

            self.handle_key(key)

def launch(ai_callback: Callable[[str], str], root_dir: str = ".", project_name: str = "ROOT_DIR",):
    def _main(stdscr):
        ui = CodoUI(
            stdscr=stdscr,
            ai_callback=ai_callback,
            root_dir=root_dir,
            project_name=project_name,
        )
        ui.run()

    locale.setlocale(locale.LC_ALL, '')
    os.environ.setdefault("TERM", "xterm-256color")
    curses.wrapper(_main)
