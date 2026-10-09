# -*- coding: utf-8 -*-
"""可独立测试的 TXT 队列与快捷键配置逻辑（无需第三方包）。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile


class QueueChangedError(RuntimeError):
    """TXT 在输出期间被别的程序修改，停止覆盖以保护用户内容。"""


@dataclass(frozen=True)
class LineTicket:
    text: str
    line_index: int
    file_digest: str


def _decode(raw: bytes) -> tuple[str, str]:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("gb18030"), "gb18030"


def _first_line(lines: list[str]) -> tuple[int, str] | None:
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n")  # 不丢失用户在行首、行末输入的空格
        if text.strip():
            return index, text
    return None


class TextLineQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> tuple[bytes, list[str], str]:
        raw = self.path.read_bytes()
        decoded, encoding = _decode(raw)
        return raw, decoded.splitlines(keepends=True), encoding

    def status(self) -> tuple[int, str | None]:
        _, lines, _ = self._read()
        count = sum(bool(line.strip()) for line in lines)
        first = _first_line(lines)
        return count, first[1] if first else None

    def peek(self) -> LineTicket | None:
        raw, lines, _ = self._read()
        first = _first_line(lines)
        if first is None:
            return None
        return LineTicket(first[1], first[0], hashlib.sha256(raw).hexdigest())

    def consume(self, ticket: LineTicket) -> int:
        """确认文件没变后，仅删除已输出的一行，原子替换原 TXT。返回剩余有效行数。"""
        raw, lines, encoding = self._read()
        if hashlib.sha256(raw).hexdigest() != ticket.file_digest:
            raise QueueChangedError("TXT 在输出期间被修改，已停止删行，请人工确认文件。")
        if not (0 <= ticket.line_index < len(lines)):
            raise QueueChangedError("TXT 行号发生变化，已停止删行。")
        if lines[ticket.line_index].rstrip("\r\n") != ticket.text:
            raise QueueChangedError("TXT 首行内容已变化，已停止删行。")
        del lines[ticket.line_index]
        content = "".join(lines).encode(encoding)
        # 临时文件必须和原文件位于同一文件夹，os.replace 才能原子替换。
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".txt_queue_", suffix=".tmp",
                dir=self.path.parent, delete=False
            ) as f:
                temp_path = Path(f.name)
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            try:
                temp_path.chmod(stat.S_IMODE(self.path.stat().st_mode))
            except OSError:
                pass
            # 临近替换前也校验，以尽可能避免覆盖外部编辑。
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != ticket.file_digest:
                raise QueueChangedError("TXT 刚被其他程序更改，已取消删行。")
            os.replace(temp_path, self.path)
            temp_path = None
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
        return sum(bool(line.strip()) for line in lines)


MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


def parse_hotkey(value: str) -> tuple[int, int]:
    """解析 Windows RegisterHotKey 所需 modifiers、虚拟键码。"""
    if not value or not value.strip():
        raise ValueError("快捷键不能为空，例如 F8 或 Ctrl+Alt+T。")
    parts = [part.strip().lower() for part in value.split("+")]
    if any(not part for part in parts):
        raise ValueError("快捷键格式错误，示例：Ctrl+Alt+T。")
    aliases = {
        "ctrl": MOD_CTRL, "control": MOD_CTRL,
        "alt": MOD_ALT, "shift": MOD_SHIFT,
        "win": MOD_WIN, "windows": MOD_WIN,
    }
    modifiers = 0
    key = None
    for part in parts:
        if part in aliases:
            if modifiers & aliases[part]:
                raise ValueError(f"重复的修饰键：{part}")
            modifiers |= aliases[part]
            continue
        if key is not None:
            raise ValueError("一个快捷键组合只能有一个主键。")
        if part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            if int(part[1:]) == 12:
                raise ValueError("F12 是 Windows 保留键，请换一个快捷键。")
            key = 0x70 + int(part[1:]) - 1
        elif len(part) == 1 and part.isascii() and part.isalnum():
            key = ord(part.upper())
        elif part == "space":
            key = 0x20
        else:
            raise ValueError(f"不支持的快捷键：{part}。支持 F1-F11、F13-F24 和字母/数字组合。")
    if key is None:
        raise ValueError("请指定一个主键，例如 F4 或 Ctrl+Alt+T。")
    if modifiers == 0 and not (0x70 <= key <= 0x87):
        raise ValueError("字母、数字、空格请搭配 Ctrl / Alt / Shift 等修饰键，避免影响正常打字。")
    return modifiers, key


def validate_hotkeys(values: dict[str, str]) -> dict[str, tuple[int, int]]:
    parsed = {name: parse_hotkey(value) for name, value in values.items()}
    if len(set(parsed.values())) != len(parsed):
        raise ValueError("鼠标连点和 TXT 输出快捷键不可重复。")
    return parsed


def parse_interval_seconds(value: str) -> float:
    try:
        parsed = float(value.strip())
    except (ValueError, AttributeError):
        raise ValueError("连点间隔需填写数字，例如 0.1 或 1.5（单位：秒）。") from None
    if not 0.01 <= parsed <= 3600:
        raise ValueError("间隔范围为 0.01 到 3600 秒。")
    return parsed
