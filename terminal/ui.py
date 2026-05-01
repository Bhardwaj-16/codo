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

ROLE_USER      = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM    = "system"
ROLE_ERROR     = "error"

class CodoUI:
    def __init__(self, stdscr, root_dir: str = "."):
        self.stdscr = stdscr
        self.root_dir = Path(root_dir).resolve()
        self.running = True
        
        self.file_tree: List[Tuple[int, str, bool, Path]] = []
        self.file_scroll = 0
        self.selected_file: Optional[Path] = None
        self.expanded_paths = set()
        
        self.metrics = {
            "cpu": [0.25, 0.40, 0.55, 0.35, 0.65, 0.50, 0.45],
            "mem_used": 0.0,
            "mem_total": 0.0,
        }
        self._metric_lock = threading.Lock()
        
        self.h = self.w = 0
        self.left_w = self.right_w = self.center_w = 0
        
        self._init_curses()
        self._compute_layout()
        self._refresh_tree()
        self._start_metrics_thread()
        
        signal.signal(signal.SIGWINCH, self._on_resize)
        self._resize_pending = False

    def _init_curses(self):
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        self.stdscr.timeout(50)
        self._setup_colors()

    def _setup_colors(self):
        curses.start_color()
        curses.use_default_colors()
        
        can_custom = curses.can_change_color() and curses.COLORS >= 256
        
        if can_custom:
            curses.init_color(16, 1000, 430, 0)
            curses.init_color(17, 180, 75, 0)
            curses.init_color(18, 450, 450, 450)
            OG = 16
            DK = 17
            DM = 18
        else:
            OG = curses.COLOR_YELLOW
            DK = curses.COLOR_BLACK
            DM = curses.COLOR_WHITE
        
        curses.init_pair(CP_ORANGE, OG, -1)
        curses.init_pair(CP_WHITE, curses.COLOR_WHITE, -1)
        curses.init_pair(CP_GREEN, curses.COLOR_GREEN, -1)
        curses.init_pair(CP_RED, curses.COLOR_RED, -1)
        curses.init_pair(CP_CYAN, curses.COLOR_CYAN, -1)
        curses.init_pair(CP_YELLOW, curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_DIM, DM, -1)
        curses.init_pair(CP_HDR, curses.COLOR_BLACK, OG)
        curses.init_pair(CP_SELECTED, curses.COLOR_BLACK, OG)

    def _on_resize(self, signum, frame):
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

    def _build_tree(self, path: Path, depth=0, max_depth=4) -> List[Tuple[int, str, bool, Path]]:
        items = []
        if depth >= max_depth:
            return items
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            skip = {"__pycache__", ".git", "node_modules", ".DS_Store"}
            for entry in entries:
                if entry.name in skip:
                    continue
                items.append((depth, entry.name, entry.is_dir(), entry))
                if entry.is_dir() and entry in self.expanded_paths:
                    items.extend(self._build_tree(entry, depth + 1, max_depth))
        except PermissionError:
            pass
        return items

    def _start_metrics_thread(self):
        def _loop():
            psutil.cpu_percent(interval=0.1)
            while self.running:
                time.sleep(1.2)
                with self._metric_lock:
                    cpu_pct = psutil.cpu_percent(interval=None) / 100.0
                    self.metrics["cpu"].append(max(0.01, min(1.0, cpu_pct)))
                    self.metrics["cpu"] = self.metrics["cpu"][-7:]
                    
                    vmem = psutil.virtual_memory()
                    self.metrics["mem_used"] = vmem.used / (1024 ** 3)
                    self.metrics["mem_total"] = vmem.total / (1024 ** 3)
        
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
        
        logo = " ORIGIN AI"
        self._safestr(self.stdscr, 0, 0, logo, curses.color_pair(CP_HDR) | curses.A_BOLD)
        
        ver = " v0.3.1 "
        self._safestr(self.stdscr, 0, len(logo), ver, curses.color_pair(CP_ORANGE) | curses.A_BOLD)
        
        ts = datetime.now().strftime("%H:%M:%S")
        dt = datetime.now().strftime("%Y-%m-%d")
        
        self._safestr(self.stdscr, 1, 0, " " * (w - 1))
        
        self._safestr(self.stdscr, 1, 1, f"▸ {self.root_dir.name}", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
        self._safestr(self.stdscr, 1, self.left_w + 2, f"DATE:{dt}  TIME:{ts}", curses.color_pair(CP_DIM))
        
        self._safestr(self.stdscr, 2, 0, H * (w - 1), curses.color_pair(CP_ORANGE))

    def draw_left_panel(self, win):
        h, w = win.getmaxyx()
        inner_h = h - 2
        
        self._draw_border(win, "FILE EXPLORER")
        
        self._safestr(win, 1, 1, f"▾ {self.root_dir.name}"[:w - 2], curses.color_pair(CP_ORANGE) | curses.A_BOLD)
        
        visible_n = inner_h - 2
        slice_ = self.file_tree[self.file_scroll: self.file_scroll + visible_n]
        
        y = 2
        for depth, name, is_dir, fpath in slice_:
            if y >= h - 1:
                break
            
            pad = "  " * depth
            if is_dir:
                prefix = "▾" if fpath in self.expanded_paths else "▸"
                label = f"{pad}{prefix} {name}/"
                attr = curses.color_pair(CP_ORANGE)
            else:
                ext = fpath.suffix.lower()
                if ext in (".py", ".ts", ".tsx", ".js", ".jsx"):
                    attr = curses.color_pair(CP_CYAN)
                elif ext in (".json", ".yaml", ".yml", ".toml"):
                    attr = curses.color_pair(CP_YELLOW)
                else:
                    attr = curses.color_pair(CP_WHITE)
                label = f"{pad}  {name}"
            
            if fpath == self.selected_file:
                attr = curses.color_pair(CP_SELECTED) | curses.A_BOLD
                label = f"{label:<{w - 2}}"
            
            self._safestr(win, y, 1, label[:w - 2], attr)
            y += 1
        
        self._safestr(win, h - 1, 1, f" {len(self.file_tree)} items "[:w - 2], curses.color_pair(CP_HDR))

    def draw_center_panel(self, win):
        h, w = win.getmaxyx()
        
        self._draw_border(win, "AI chat")
        
        msg = "chat area"
        self._safestr(win, h // 2 - 1, (w - len(msg)) // 2, msg, curses.color_pair(CP_DIM))

    def draw_right_panel(self, win):
        h, w = win.getmaxyx()
        inner_w = w - 2
        
        self._draw_border(win, "SYS METRICS")
        
        y = 1
        
        with self._metric_lock:
            cpu = list(self.metrics["cpu"])
            mem_used = self.metrics["mem_used"]
            mem_total = self.metrics["mem_total"]
        
        if y < h - 1:
            self._safestr(win, y, 1, "CPU", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
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
            cp = CP_GREEN if avg < 0.5 else CP_YELLOW if avg < 0.75 else CP_RED
            self._hbar(win, y, 1, inner_w - 1, avg, cp)
            y += 2
        
        if y < h - 1:
            self._safestr(win, y, 1, "MEMORY", curses.color_pair(CP_ORANGE) | curses.A_BOLD)
            mem_str = f"{mem_used:.1f} GB"
            self._safestr(win, y, inner_w - len(mem_str), mem_str, curses.color_pair(CP_CYAN) | curses.A_BOLD)
            y += 1
        
        if y < h - 1 and mem_total > 0:
            self._hbar(win, y, 1, inner_w - 1, mem_used / mem_total, CP_CYAN)
            y += 1
        
        if y < h - 1:
            used_s = f"USED:{mem_used:.1f}G"
            total_s = f"TOTAL:{mem_total:.0f}G"
            self._safestr(win, y, 1, used_s, curses.color_pair(CP_DIM))
            self._safestr(win, y, inner_w - len(total_s), total_s, curses.color_pair(CP_DIM))

    def draw(self):
        if self._resize_pending:
            self._resize_pending = False
            self._compute_layout()
            self.stdscr.clear()
            self.stdscr.refresh()

        h, w = self.h, self.w

        if h < 12 or w < 70:
            self.stdscr.erase()
            msg = "Terminal too small - please resize"
            self._safestr(self.stdscr, h // 2, max(0, (w - len(msg)) // 2), msg,
                          curses.color_pair(CP_RED) | curses.A_BOLD)
            self.stdscr.refresh()
            return
        
        HEADER_H = 3
        panel_y = HEADER_H
        panel_h = max(1, h - HEADER_H)

        self.draw_header()

        try:
            left_win = curses.newwin(panel_h, self.left_w, panel_y, 0)
            center_win = curses.newwin(panel_h, self.center_w, panel_y, self.left_w)
            right_win = curses.newwin(panel_h, self.right_w, panel_y, self.left_w + self.center_w)

            left_win.erase()
            self.draw_left_panel(left_win)
            left_win.noutrefresh()

            center_win.erase()
            self.draw_center_panel(center_win)
            center_win.noutrefresh()

            right_win.erase()
            self.draw_right_panel(right_win)
            right_win.noutrefresh()

            self.stdscr.noutrefresh()
            curses.doupdate()
        except curses.error:
            pass

    def handle_key(self, key: int):
        if key == ord('q'):
            self.running = False
            return

        if key == curses.KEY_UP:
            self.file_scroll = max(0, self.file_scroll - 1)
        elif key == curses.KEY_DOWN:
            max_scroll = max(0, len(self.file_tree) - 1)
            self.file_scroll = min(self.file_scroll + 1, max_scroll)
        elif key == curses.KEY_PPAGE:
            self.file_Scroll = max(0, self.file_scroll - 10)
        elif key == curses.KEYNPAGE:
            max_scroll = max(0, len(self.file_tree) - 1)
            self.file_scroll = min(self.file_scroll + 10, max_scroll)
        elif key in (ord('\n'), ord('\r'), curses.KEY_ENTER):
            if 0 <= self.file_scroll < len(self.file_tree):
                depth, name, is_dir, fpath = self.file_tree[self.file_scroll]
                self.selected_file = fpath
                if is_dir:
                    if fpath in self.expanded_paths:
                        self.expanded_paths.remove(fpath)
                    else:
                        self.expanded_paths.add(fpath)
                    self._refresh_tree()

    def run(self):
        while self.running:
            self.draw()

            try:
                key = self.stdscr.getch()
            except curses.error:
                key = -1

            if key == -1:
                time.sleep(0.016)
                continue
            
            if key == curses.KEY_RESIZE:
                self._resize_pending = True
                continue

            self.handle_key(key)

def main(stdscr):
    locale.setlocale(locale.LC_ALL, '')
    ui = CodoUI(stdscr, root_dir = ".")
    ui.run()

if __name__ == "__main__":
    os.environ.setdefault("TERM", "xterm-256color")
    curses.wrapper(main)
