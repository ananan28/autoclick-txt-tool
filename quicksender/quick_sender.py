"""QuickSender 自动存档版。F4 在邮箱/话术间交替粘贴。"""
from __future__ import annotations

from dataclasses import replace
import ctypes
import os
import queue
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

import keyboard
import pyperclip

from quick_sender_core import Snapshot, StateStore, active_lines, next_item, normalize, read_text_file


def log_exception(exc_type, exc_value, exc_traceback):
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        store = StateStore()
        store.directory.mkdir(parents=True, exist_ok=True)
        log_path = store.directory / "error_log.txt"
        log_path.write_text(details, encoding="utf-8")
        messagebox.showerror("QuickSender 错误", f"遇到异常，错误日志位于：\n{log_path}\n\n{exc_value}")
    except Exception:
        print(details, file=sys.stderr)


sys.excepthook = log_exception


class QuickSenderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("QuickSender 2.3 · 邮箱连点器")
        self.root.geometry("860x600")
        self.root.minsize(690, 450)
        self.store = StateStore()
        self.state = Snapshot()
        self.f4_events = queue.SimpleQueue()
        self.hotkey_handle = None
        self.poll_after_id = None
        self.save_after_id = None
        self.loading = False
        self.closing = False
        self.setup_ui()
        self.restore_last_session()
        self.register_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        tk.Label(
            self.root,
            text="F4 邮箱：自动从原 TXT 删掉已用行｜F4 话术：轮换但绝不删行｜实时存档",
            font=("微软雅黑", 10, "bold"), fg="#173e61", pady=12,
        ).pack(fill=tk.X)

        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=13, pady=(0, 5))
        tk.Button(top, text="💾 立即存档", command=self.save_now).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top, text="📁 打开存档目录", command=self.open_state_folder).pack(side=tk.LEFT)
        self.info = tk.Label(top, text="存档目录：%APPDATA%\\QuickSender", fg="#5b6877")
        self.info.pack(side=tk.RIGHT)

        columns = tk.Frame(self.root)
        columns.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        left = tk.LabelFrame(columns, text="左栏｜邮箱 TXT（用一条删一条）", fg="#1e4c9a", font=("微软雅黑", 10))
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Button(left, text="📂 选择邮箱 TXT", bg="#e4f3ff", command=self.load_emails).pack(fill=tk.X, padx=7, pady=6)
        self.email_source = tk.Label(left, text="尚未关联原始 TXT", anchor="w", fg="#777", wraplength=320)
        self.email_source.pack(fill=tk.X, padx=8)
        email_frame = tk.Frame(left)
        email_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        scroll1 = tk.Scrollbar(email_frame)
        scroll1.pack(side=tk.RIGHT, fill=tk.Y)
        self.email_text = tk.Text(email_frame, width=32, font=("Consolas", 10), undo=True, yscrollcommand=scroll1.set)
        self.email_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll1.config(command=self.email_text.yview)

        right = tk.LabelFrame(columns, text="右栏｜话术 TXT（轮换且不删）", fg="#197046", font=("微软雅黑", 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Button(right, text="📂 选择话术 TXT", bg="#e1f5e9", command=self.load_words).pack(fill=tk.X, padx=7, pady=6)
        self.words_source = tk.Label(right, text="尚未关联原始 TXT", anchor="w", fg="#777", wraplength=320)
        self.words_source.pack(fill=tk.X, padx=8)
        words_frame = tk.Frame(right)
        words_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        scroll2 = tk.Scrollbar(words_frame)
        scroll2.pack(side=tk.RIGHT, fill=tk.Y)
        self.words_text = tk.Text(words_frame, width=32, font=("微软雅黑", 10), undo=True, yscrollcommand=scroll2.set)
        self.words_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll2.config(command=self.words_text.yview)

        self.next_label = tk.Label(self.root, text="下一次 F4：邮箱", font=("微软雅黑", 10, "bold"), fg="#174d7b", anchor="w")
        self.next_label.pack(fill=tk.X, padx=14, pady=(3, 0))
        self.status = tk.Label(self.root, text="请载入两个 TXT 文件，再点击其他程序的输入框并按 F4。", bd=1,
                               relief=tk.SUNKEN, anchor="w", font=("微软雅黑", 9), fg="#34495e")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        for widget in (self.email_text, self.words_text):
            widget.bind("<<Modified>>", self.on_text_modified)
            widget.edit_modified(False)

    def set_status(self, text, color="#34495e"):
        self.status.config(text=" " + text, fg=color)
        self.refresh_next_label()

    def refresh_next_label(self):
        state = normalize(self.state)
        if state.f4_state == 0:
            text = f"下一次 F4：邮箱　｜　剩余 {len(active_lines(self.email_text.get('1.0', 'end-1c')))} 条邮箱"
            color = "#1e4c9a"
        else:
            count = len(active_lines(self.words_text.get('1.0', 'end-1c')))
            text = f"下一次 F4：话术第 {state.words_index + 1 if count else 0} 条／共 {count} 条"
            color = "#197046"
        self.next_label.config(text=text, fg=color)

    def set_text(self, widget, text: str):
        self.loading = True
        try:
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
            widget.edit_modified(False)
        finally:
            self.loading = False

    def from_ui(self):
        # 不自动删除用户输入的换行，保持原 TXT 对应关系。
        return normalize(replace(self.state, email_text=self.email_text.get("1.0", "end-1c"),
                                 words_text=self.words_text.get("1.0", "end-1c")))

    def refresh_source_labels(self):
        self.email_source.config(text=self.state.email_path or "尚未关联原始 TXT")
        self.words_source.config(text=self.state.words_path or "尚未关联原始 TXT")
        self.refresh_next_label()

    def cancel_scheduled_save(self):
        if self.save_after_id is not None:
            self.root.after_cancel(self.save_after_id)
            self.save_after_id = None

    def persist_ui(self, show_error=False):
        self.cancel_scheduled_save()
        candidate = self.from_ui()
        try:
            self.state = self.store.save(candidate)
            return True
        except Exception as e:
            self.set_status(f"自动存档失败：{e}", "red")
            if show_error:
                messagebox.showerror("无法保存", f"存档未完整写回，请检查 TXT 文件权限或文件是否被占用：\n{e}")
            return False

    def on_text_modified(self, event):
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        if self.loading or self.closing:
            return
        self.cancel_scheduled_save()
        # 每次停止键入 250ms 后保存；关闭窗口 / F4 会立即保存。
        self.save_after_id = self.root.after(250, self.auto_save)

    def auto_save(self):
        self.save_after_id = None
        if not self.closing:
            if self.persist_ui():
                self.set_status("修改已自动存档，并同步到原始 TXT。", "#197046")

    def save_now(self):
        if self.persist_ui(show_error=True):
            self.set_status("存档成功：原始 TXT + 断点位置均已保存。", "#197046")

    def restore_last_session(self):
        try:
            stored = self.store.load()
        except Exception as e:
            messagebox.showwarning("读取存档失败", f"无法读取上次进度：{e}\n请重新选择 TXT；重新保存前如需保留旧存档，请先备份 state.json。")
            return
        if stored is None:
            return
        # Restore the last saved window contents and F4 position exactly.
        # Do not reload external TXT or write files during startup.
        self.state = normalize(stored)
        self.set_text(self.email_text, self.state.email_text)
        self.set_text(self.words_text, self.state.words_text)
        self.refresh_source_labels()
        self.set_status("已恢复关闭时的内容和位置，继续按 F4 即可。", "#197046")

    def load_emails(self):
        self.load_file("email")

    def load_words(self):
        self.load_file("words")

    def load_file(self, kind):
        self.cancel_scheduled_save()
        current = self.from_ui()
        path = filedialog.askopenfilename(title=("选择邮箱 TXT" if kind == "email" else "选择话术 TXT"),
                                          filetypes=[("文本文件", "*.txt"), ("全部文件", "*.*")])
        if not path:
            self.save_after_id = self.root.after(250, self.auto_save)
            return
        path = os.path.abspath(path)
        other = self.state.words_path if kind == "email" else self.state.email_path
        if other and os.path.normcase(path) == os.path.normcase(os.path.abspath(other)):
            messagebox.showerror("不能使用相同文件", "邮箱与话术必须选择不同的 TXT，防止相互覆盖。")
            return
        try:
            content, encoding = read_text_file(path)
            if kind == "email":
                updated = replace(current, email_path=path, email_text=content,
                                  email_encoding=encoding, f4_state=0)
            else:
                updated = replace(current, words_path=path, words_text=content,
                                  words_encoding=encoding, words_index=0)
            # 初次选择文件保存当前会话。
            updated = self.store.save(updated, sync_paths=())
            self.state = updated
            if kind == "email":
                self.set_text(self.email_text, content)
            else:
                self.set_text(self.words_text, content)
            self.refresh_source_labels()
            self.set_status("TXT 已关联并存档；之后的修改会自动写回此文件。", "#197046")
        except Exception as e:
            messagebox.showerror("载入失败", f"未能载入 TXT：\n{e}")

    def register_hotkey(self):
        try:
            self.hotkey_handle = keyboard.add_hotkey(
                "f4", lambda: self.f4_events.put(1), suppress=True, trigger_on_release=True
            )
        except Exception as e:
            messagebox.showerror("快捷键未注册", f"F4 注册失败：\n{e}\n请尝试以管理员身份运行。")
        self.poll_after_id = self.root.after(40, self.poll_hotkeys)

    def poll_hotkeys(self):
        if self.closing:
            return
        for _ in range(12):
            try:
                self.f4_events.get_nowait()
            except queue.Empty:
                break
            self.handle_f4()
        self.poll_after_id = self.root.after(40, self.poll_hotkeys)

    def main_window_foreground(self):
        if sys.platform != "win32":
            return False
        try:
            user32 = ctypes.windll.user32
            current = user32.GetForegroundWindow()
            own = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            return current == own
        except Exception:
            return False

    def handle_f4(self):
        # 避免用户在 QuickSender 窗口内按 F4，把内容粘到自己的列表导致错乱。
        if self.main_window_foreground():
            self.set_status("请先点击目标软件的输入框，再按 F4。", "#a36915")
            return
        current = self.from_ui()
        if not current.email_path or not current.words_path:
            self.set_status("请先分别载入邮箱 TXT 和话术 TXT。", "red")
            return
        try:
            item, advanced = next_item(current)
        except ValueError as e:
            self.set_status(str(e), "red")
            return

        try:
            # 先把内容放入剪贴板，确保能够复制；如果失败，进度不推进。
            pyperclip.copy(item)
            # 先记录已使用这一条，再向外部窗口粘贴，以减少崩溃重发风险。
            committed = self.store.save(advanced)
        except Exception as e:
            self.set_status(f"F4 已取消，存档/复制失败：{e}", "red")
            messagebox.showerror("未执行粘贴", f"剪贴板或存档出错，本次没有调用粘贴：\n{e}")
            return

        self.cancel_scheduled_save()
        self.state = committed
        self.set_text(self.email_text, committed.email_text)
        self.set_text(self.words_text, committed.words_text)
        try:
            keyboard.send("ctrl+v")
        except Exception as e:
            self.set_status("粘贴失败，但内容已复制且进度已记录。请到目标窗口手动 Ctrl+V。", "red")
            messagebox.showwarning("手动粘贴", f"没有成功自动粘贴：{e}\n内容已在剪贴板，可手动 Ctrl+V。\n为避免重复，进度已推进。")
            return
        if current.f4_state == 0:
            remaining = len(active_lines(committed.email_text))
            self.set_status(f"邮箱已粘贴，已同步删除原邮箱 TXT 中的这一行，剩余 {remaining} 条。", "#197046")
        else:
            self.set_status("话术已粘贴，原话术 TXT 未删除任何一行；轮换位置已保存。", "#197046")

    def open_state_folder(self):
        self.store.directory.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(self.store.directory)
        else:
            messagebox.showinfo("存档位置", str(self.store.directory))

    def on_closing(self):
        # 若用户正在输入，必须先直接存档，不能仅等 250ms 的定时器。
        if not self.persist_ui(show_error=True):
            if not messagebox.askyesno("尚未保存", "自动存档未成功。仍要退出吗？\n部分最新修改可能没有保存到原始 TXT。"):
                return
        self.closing = True
        self.cancel_scheduled_save()
        if self.poll_after_id is not None:
            self.root.after_cancel(self.poll_after_id)
        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    main = tk.Tk()
    main.report_callback_exception = log_exception
    QuickSenderApp(main)
    main.mainloop()
