# -*- coding: utf-8 -*-
"""仅两个功能：可调间隔鼠标连点；按快捷键逐行输入并从 TXT 删除已用行。
运行环境：Windows 10/11，Python 3.9+；只使用 Python 标准库。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from automation_core import TextLineQueue, parse_interval_seconds, validate_hotkeys

if sys.platform != 'win32':
    raise SystemExit('此工具需要 Windows 10/11 环境。')

from windows_input import HotkeyListener, MOUSE_FLAGS, click_mouse, foreground_is_this_app, send_text

TITLE = '双功能工具：自动连点 + TXT逐行输入 v3.0'
DEFAULT_SETTINGS = {
    'click_hotkey': 'F8',
    'click_interval': '0.1',
    'click_button': '左键',
    'text_hotkey': 'F4',
    'txt_path': '',
}


def settings_path() -> Path:
    """Windows 用户目录下的设置，EXE 放到任意目录都可保存。"""
    base = Path(os.environ.get('APPDATA') or Path.home())
    return base / 'ClickTxtTwoFunctions' / 'settings.json'


def key_map(data: dict[str, str]) -> dict[str, tuple[int, int]]:
    return validate_hotkeys({'mouse': data['click_hotkey'], 'text': data['text_hotkey']})


def load_settings() -> dict[str, str]:
    cfg = DEFAULT_SETTINGS.copy()
    try:
        p = settings_path()
        if p.is_file():
            disk = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(disk, dict):
                for field in cfg:
                    if isinstance(disk.get(field), str):
                        cfg[field] = disk[field]
        parse_interval_seconds(cfg['click_interval'])
        key_map(cfg)
        if cfg['click_button'] not in MOUSE_FLAGS:
            raise ValueError('无效鼠标按键')
    except (ValueError, OSError, json.JSONDecodeError):
        cfg = DEFAULT_SETTINGS.copy()
    return cfg


def save_settings(cfg: dict[str, str]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


class MouseClicker:
    """后台连点循环，不阻塞界面，并可立即停止。"""

    def __init__(self, event_queue: queue.Queue):
        self.events = event_queue
        self.active = threading.Event()
        self.closing = threading.Event()
        self.wake = threading.Event()
        self._lock = threading.Lock()
        self.interval = 0.1
        self.button = '左键'
        self.thread = threading.Thread(target=self._run, name='MouseClicker', daemon=True)
        self.thread.start()

    def configure(self, interval: float, button: str) -> None:
        with self._lock:
            self.interval, self.button = interval, button

    def _run(self) -> None:
        while not self.closing.is_set():
            if not self.active.wait(0.05):
                continue
            with self._lock:
                seconds, button = self.interval, self.button
            if not self.active.is_set():
                continue
            self.wake.clear()
            try:
                click_mouse(button)
            except Exception as exc:
                self.active.clear()
                self.events.put(('error', f'鼠标连点自动停止：{exc}'))
            self.wake.wait(seconds)

    def start(self) -> None:
        self.active.set()
        self.wake.set()

    def stop(self) -> None:
        self.active.clear()
        self.wake.set()

    def close(self) -> None:
        self.active.clear()
        self.closing.set()
        self.wake.set()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.messages = queue.Queue()
        self.config = load_settings()
        self.pending_config = None
        self.vars = {k: tk.StringVar(value=v) for k, v in self.config.items()}
        self.clicker = MouseClicker(self.messages)
        self.clicker.configure(float(self.config['click_interval']), self.config['click_button'])
        self.listener = None
        self._build_ui()
        self.update_txt_status()
        self._refresh_click_status()
        self.listener = HotkeyListener(self.messages, key_map(self.config))
        self.listener.start()
        self.log('软件已启动。默认 F8 开关连点，F4 每按一次仅输入 TXT 的一行。')
        self.log('先选好 TXT，再点击其他程序的输入框，然后按 TXT 快捷键。')
        self.root.after(60, self._poll_messages)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def _build_ui(self) -> None:
        root = self.root
        root.title(TITLE)
        root.geometry('630x510')
        root.minsize(565, 480)
        root.configure(bg='#f4f7fb')
        style = ttk.Style()
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        base = ttk.Frame(root, padding=16)
        base.pack(fill='both', expand=True)
        ttk.Label(base, text='自动连点 + TXT 单次输入', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(base, text='只有两个功能，所有设置直接在这里修改。', foreground='#52677c').pack(anchor='w', pady=(2, 12))

        mouse = ttk.LabelFrame(base, text='① 鼠标自动连点', padding=12)
        mouse.pack(fill='x', pady=(0, 12))
        fields = ttk.Frame(mouse)
        fields.pack(fill='x')
        ttk.Label(fields, text='开关快捷键').grid(row=0, column=0, sticky='w')
        ttk.Entry(fields, textvariable=self.vars['click_hotkey'], width=13).grid(row=0, column=1, sticky='w', padx=(8, 20))
        ttk.Label(fields, text='点击间隔（秒）').grid(row=0, column=2, sticky='w')
        ttk.Entry(fields, textvariable=self.vars['click_interval'], width=10).grid(row=0, column=3, sticky='w', padx=(8, 0))
        ttk.Label(fields, text='鼠标按键').grid(row=1, column=0, sticky='w', pady=(12, 0))
        ttk.Combobox(fields, textvariable=self.vars['click_button'], values=list(MOUSE_FLAGS), width=10, state='readonly').grid(row=1, column=1, sticky='w', padx=(8, 20), pady=(12, 0))
        self.mouse_btn = ttk.Button(fields, text='开始连点', command=self.toggle_click)
        self.mouse_btn.grid(row=1, column=2, columnspan=2, sticky='w', pady=(12, 0))
        self.mouse_status = ttk.Label(mouse, text='', foreground='#0b6f53')
        self.mouse_status.pack(anchor='w', pady=(11, 0))

        txt = ttk.LabelFrame(base, text='② TXT 每按一次快捷键只输入一行', padding=12)
        txt.pack(fill='x', pady=(0, 12))
        line = ttk.Frame(txt)
        line.pack(fill='x')
        ttk.Button(line, text='载入 TXT 文件', command=self.select_txt).pack(side='left')
        self.file_label = ttk.Label(line, text='尚未选择 TXT', foreground='#4d6479')
        self.file_label.pack(side='left', padx=(12, 0), fill='x', expand=True)
        line2 = ttk.Frame(txt)
        line2.pack(fill='x', pady=(12, 0))
        ttk.Label(line2, text='单次输入快捷键').pack(side='left')
        ttk.Entry(line2, textvariable=self.vars['text_hotkey'], width=16).pack(side='left', padx=(9, 0))
        self.txt_status = ttk.Label(txt, text='', foreground='#0b6f53')
        self.txt_status.pack(anchor='w', pady=(10, 0))
        ttk.Label(txt, text='每次按键：输入当前第一条非空内容 → 从原 TXT 删除该行。不会自动按 Enter、Tab，也不会删除整个 TXT 文件。', foreground='#6a5460', wraplength=560).pack(anchor='w', pady=(5, 0))

        bar = ttk.Frame(base)
        bar.pack(fill='x', pady=(0, 12))
        ttk.Button(bar, text='应用并保存设置', command=self.apply_settings).pack(side='left')
        ttk.Label(bar, text='例：F8、F4、Ctrl+Alt+T', foreground='#52677c').pack(side='right')

        logs = ttk.LabelFrame(base, text='状态', padding=8)
        logs.pack(fill='both', expand=True)
        self.logbox = tk.Text(logs, height=5, font=('Microsoft YaHei UI', 9), wrap='word', state='disabled')
        self.logbox.pack(fill='both', expand=True)

    def log(self, msg: str) -> None:
        self.logbox.configure(state='normal')
        self.logbox.insert('end', msg + '\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def _refresh_click_status(self) -> None:
        enabled = self.clicker.active.is_set()
        self.mouse_btn.configure(text='停止连点' if enabled else '开始连点')
        self.mouse_status.configure(text=('正在连点' if enabled else '已停止') + f"｜{self.config['click_button']}｜间隔 {self.config['click_interval']} 秒")

    def toggle_click(self) -> None:
        active = not self.clicker.active.is_set()
        if active:
            self.clicker.start()
        else:
            self.clicker.stop()
        self._refresh_click_status()
        self.log('鼠标连点已' + ('开始。' if active else '停止。'))

    def select_txt(self) -> None:
        path = filedialog.askopenfilename(title='选择 TXT 文档', filetypes=[('TXT 文件', '*.txt')])
        if not path:
            return
        try:
            count, _ = TextLineQueue(path).status()
        except (OSError, UnicodeError) as exc:
            messagebox.showerror('读取 TXT 失败', str(exc))
            return
        self.config['txt_path'] = path
        self.vars['txt_path'].set(path)
        try:
            save_settings(self.config)
        except OSError as exc:
            self.log(f'TXT 已载入，但保存路径设置失败：{exc}')
        self.update_txt_status()
        self.log(f'已载入 {Path(path).name}，还有 {count} 行可输入。')

    def update_txt_status(self) -> None:
        path = self.config['txt_path']
        self.file_label.configure(text=Path(path).name if path else '尚未选择 TXT')
        if not path:
            self.txt_status.configure(text='剩余：—')
            return
        try:
            count, _ = TextLineQueue(path).status()
            self.txt_status.configure(text=f'剩余可输入：{count} 行')
        except (OSError, UnicodeError) as exc:
            self.txt_status.configure(text='TXT 文件不可读取')
            self.log(f'TXT 状态获取失败：{exc}')

    def send_one_line(self) -> None:
        path = self.config['txt_path']
        if not path:
            self.log('请先点击“载入 TXT 文件”。')
            return
        if foreground_is_this_app():
            self.log('请先点到其他程序的输入框，再按 TXT 快捷键。')
            return
        # 防止后台持续点击导致文本输入焦点被移走。
        mouse_was_active = self.clicker.active.is_set()
        if mouse_was_active:
            self.clicker.stop()
        try:
            store = TextLineQueue(path)
            ticket = store.peek()
            if ticket is None:
                self.log('TXT 已全部输入完毕。')
                return
            send_text(ticket.text)  # Windows Unicode 键盘事件，支持中英文，不使用剪贴板。
            remaining = store.consume(ticket)  # 仅在输入事件发送成功后删这一行。
            self.log(f'已输入 1 行，并从原 TXT 删除；剩余 {remaining} 行。')
        except Exception as exc:
            self.log(f'此行未完整处理：{exc}。如目标输入框已有文字，请先核对 TXT 再按快捷键。')
        finally:
            if mouse_was_active:
                self.clicker.start()
            self.update_txt_status()
            self._refresh_click_status()

    def apply_settings(self) -> None:
        if self.pending_config is not None:
            self.log('快捷键设置正在应用中，请稍候。')
            return
        try:
            cfg = {k: v.get().strip() for k, v in self.vars.items()}
            cfg['click_interval'] = cfg['click_interval'].replace('，', '.')
            parse_interval_seconds(cfg['click_interval'])
            if cfg['click_button'] not in MOUSE_FLAGS:
                raise ValueError('鼠标按键只能选左键、右键或中键。')
            cfg['txt_path'] = self.config['txt_path']
            key_map(cfg)
            self.pending_config = cfg
            self.listener.update_bindings(key_map(cfg))
        except (ValueError, OSError) as exc:
            self.pending_config = None
            messagebox.showerror('设置错误', str(exc))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'hotkey':
                    if value == 'mouse':
                        self.toggle_click()
                    elif value == 'text':
                        self.send_one_line()
                elif kind == 'bound':
                    if self.pending_config is None:
                        self.log('两个全局快捷键注册成功。')
                    else:
                        self.config = self.pending_config
                        self.pending_config = None
                        self.clicker.configure(float(self.config['click_interval']), self.config['click_button'])
                        self._refresh_click_status()
                        try:
                            save_settings(self.config)
                            self.log('两个快捷键与连点设置已保存并生效。')
                        except OSError as exc:
                            self.log(f'新设置已生效，但本地保存失败：{exc}')
                elif kind == 'error':
                    self.log('错误：' + str(value))
                    if self.pending_config is not None:
                        self.pending_config = None
                        for key, var in self.vars.items():
                            var.set(self.config[key])
                        self.log('无法应用新快捷键，已恢复之前的设置。')
        except queue.Empty:
            pass
        self.root.after(60, self._poll_messages)

    def close(self) -> None:
        self.clicker.close()
        if self.listener:
            self.listener.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
