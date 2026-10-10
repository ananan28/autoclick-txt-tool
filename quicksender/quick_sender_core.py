"""QuickSender 进度管理模块。仅使用 Python 标准库。"""
from __future__ import annotations

from dataclasses import dataclass, replace, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile


@dataclass
class Snapshot:
    version: int = 2
    email_path: str = ""
    words_path: str = ""
    email_text: str = ""
    words_text: str = ""
    email_encoding: str = "utf-8"
    words_encoding: str = "utf-8"
    f4_state: int = 0                  # 0: 下次邮箱；1: 下次话术
    words_index: int = 0               # 下一条话术的 0 起始序号
    saved_at: str = ""


def active_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize(snapshot: Snapshot) -> Snapshot:
    count = len(active_lines(snapshot.words_text))
    return replace(snapshot,
                   f4_state=1 if snapshot.f4_state == 1 else 0,
                   words_index=(snapshot.words_index % count if count else 0))


def next_item(snapshot: Snapshot) -> tuple[str, Snapshot]:
    """返回应粘贴的内容和粘贴*前*需要落盘的新进度。"""
    snapshot = normalize(snapshot)
    if snapshot.f4_state == 0:
        lines = snapshot.email_text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            item = line.strip()
            if item:
                # 保留其他邮箱和话术的原始内容；只删已使用邮箱那行。
                remainder = "".join(lines[i + 1:])
                return item, replace(snapshot, email_text=remainder, f4_state=1)
        raise ValueError("邮箱列表为空，请载入或补充邮箱 TXT。")

    words = active_lines(snapshot.words_text)
    if not words:
        raise ValueError("话术列表为空，请载入或补充话术 TXT。")
    idx = snapshot.words_index
    return words[idx], replace(snapshot, words_index=(idx + 1) % len(words), f4_state=0)


def read_text_file(path: str) -> tuple[str, str]:
    data = Path(path).read_bytes()
    encodings = ("utf-8-sig",) if data.startswith(b"\xef\xbb\xbf") else ("utf-8", "gb18030")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            # Tk 的 Text 统一使用 \n，写回时在 Windows 上由操作系统生成 CRLF。
            return text.replace("\r\n", "\n").replace("\r", "\n"), encoding
        except UnicodeDecodeError:
            pass
    raise UnicodeError("无法识别 TXT 文件编码，请将文件另存为 UTF-8。")


def data_directory() -> Path:
    # exe 放在 Program Files 等只读目录也能保存进度。
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "QuickSender"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".quicksender_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def backup_once(path: str) -> str:
    """第一次修改前留原始 TXT 备份（不会覆盖历史备份）。"""
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"原始 TXT 不存在：{src}")
    backup = src.with_name(src.name + ".QuickSender原始备份.txt")
    if backup.exists():
        return str(backup)
    try:
        with src.open("rb") as inp, backup.open("xb") as out:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
    except FileExistsError:
        pass
    except Exception:
        # 防止留下不完整的首次备份文件
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return str(backup)


class StateStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory is not None else data_directory()
        self.path = self.directory / "state.json"

    def load(self) -> Snapshot | None:
        if not self.path.is_file():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 2:
            raise ValueError("存档版本不兼容。")
        allowed = {k for k in Snapshot.__dataclass_fields__}
        restored = Snapshot(**{k: v for k, v in data.items() if k in allowed})
        if not isinstance(restored.email_text, str) or not isinstance(restored.words_text, str):
            raise ValueError("存档内容格式无效。")
        if not isinstance(restored.words_index, int) or not isinstance(restored.f4_state, int):
            raise ValueError("存档计数格式无效。")
        return normalize(restored)

    def save(self, snapshot: Snapshot) -> Snapshot:
        snapshot = normalize(snapshot)
        if snapshot.email_path and snapshot.words_path:
            if os.path.normcase(os.path.abspath(snapshot.email_path)) == os.path.normcase(os.path.abspath(snapshot.words_path)):
                raise ValueError("邮箱和话术不能使用同一个 TXT 文件，否则会互相覆盖。")

        # 确保备份成功，才允许修改源 TXT 或更新进度。
        for path in (snapshot.email_path, snapshot.words_path):
            if path:
                backup_once(path)

        snapshot = replace(snapshot, saved_at=datetime.now(timezone.utc).isoformat())
        payload = json.dumps(asdict(snapshot), ensure_ascii=False, indent=2).encode("utf-8")
        # 进度必须先落盘，再可能向其他程序粘贴。
        # 如果意外中断，更偏向于跳过某条，也不重新发送已处理的条目。
        atomic_write_bytes(self.path, payload)

        for path, content, encoding in (
            (snapshot.email_path, snapshot.email_text, snapshot.email_encoding),
            (snapshot.words_path, snapshot.words_text, snapshot.words_encoding),
        ):
            if not path:
                continue
            dest = Path(path)
            with dest.open("rb") as f:
                original = f.read()
            try:
                data = content.replace("\n", os.linesep).encode(encoding)
            except UnicodeEncodeError:
                # GBK 老文档新输入了 emoji 等字符时转 UTF-8，绝不丢字。
                data = content.replace("\n", os.linesep).encode("utf-8-sig")
                if path == snapshot.email_path:
                    snapshot.email_encoding = "utf-8-sig"
                else:
                    snapshot.words_encoding = "utf-8-sig"
            if original != data:
                atomic_write_bytes(dest, data)
        # 少见的编码自动转型：把新的编码也同步到存档。
        if snapshot.email_encoding != json.loads(payload).get("email_encoding") or snapshot.words_encoding != json.loads(payload).get("words_encoding"):
            atomic_write_bytes(self.path, json.dumps(asdict(snapshot), ensure_ascii=False, indent=2).encode("utf-8"))
        return snapshot

    def differing_files(self, snapshot: Snapshot) -> list[str]:
        """用于检测软件关闭期间对原 TXT 的手动改动。"""
        different = []
        for path, content in ((snapshot.email_path, snapshot.email_text), (snapshot.words_path, snapshot.words_text)):
            if not path:
                continue
            try:
                actual, _ = read_text_file(path)
                if actual != content:
                    different.append(path)
            except (OSError, UnicodeError):
                different.append(path)
        return different
