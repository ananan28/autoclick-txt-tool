"""无真实键盘操作的 Tk 界面冒烟测试。Linux 可执行 xvfb-run -a python test_gui_smoke.py。"""
from pathlib import Path
import os
import sys
import tempfile
import types
import tkinter as tk

clip = {'text': '', 'pasted': []}
keyboard = types.ModuleType('keyboard')
keyboard.add_hotkey = lambda *args, **kwargs: 123
keyboard.remove_hotkey = lambda *args, **kwargs: None
keyboard.send = lambda keys: clip['pasted'].append((keys, clip['text']))
sys.modules['keyboard'] = keyboard
pyperclip = types.ModuleType('pyperclip')
pyperclip.copy = lambda value: clip.__setitem__('text', value)
sys.modules['pyperclip'] = pyperclip

from quick_sender import QuickSenderApp, filedialog

# Simulate external target focus; fail to stderr without opening modal dialogs.
QuickSenderApp.main_window_foreground = lambda self: False
sys.excepthook = sys.__excepthook__

with tempfile.TemporaryDirectory() as temp:
    os.environ['APPDATA'] = temp
    path = Path(temp)
    emails = path / 'emails.txt'
    words = path / 'words.txt'
    emails.write_text('one@example.com\ntwo@example.com\n', encoding='utf-8')
    words.write_text('第一条话术\n第二条话术\n', encoding='utf-8')
    original_words = words.read_bytes()

    gui = tk.Tk()
    app = QuickSenderApp(gui)
    gui.update()
    # 验证实际「选择邮箱 TXT」「选择话术 TXT」UI 按钮的载入路径。
    paths = iter([str(emails), str(words)])
    filedialog.askopenfilename = lambda **kwargs: next(paths)
    app.load_emails()
    app.load_words()
    assert app.state.email_path == str(emails)
    assert app.state.words_path == str(words)

    app.handle_f4()  # 邮箱1
    assert clip['pasted'][-1][1] == 'one@example.com'
    assert emails.read_text(encoding='utf-8') == 'two@example.com\n'
    assert words.read_bytes() == original_words
    app.handle_f4()  # 话术1
    assert clip['pasted'][-1][1] == '第一条话术'
    assert emails.read_text(encoding='utf-8') == 'two@example.com\n'
    assert words.read_bytes() == original_words
    app.on_closing()

    gui2 = tk.Tk()   # 模拟完全退出并重新启动 EXE
    app2 = QuickSenderApp(gui2)
    gui2.update()
    assert app2.state.f4_state == 0
    assert app2.state.words_index == 1
    assert app2.email_text.get('1.0', 'end-1c').strip() == 'two@example.com'
    app2.handle_f4()  # 邮箱2
    assert clip['pasted'][-1][1] == 'two@example.com'
    assert emails.read_text(encoding='utf-8') == ''
    assert words.read_bytes() == original_words
    app2.handle_f4()  # 话术2
    assert clip['pasted'][-1][1] == '第二条话术'
    assert words.read_bytes() == original_words
    app2.on_closing()
    print('GUI import/F4/TXT delete/no-delete/restart tests passed')
