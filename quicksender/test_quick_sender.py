"""开发时执行：python -m unittest -v test_quick_sender.py"""
from dataclasses import replace
from pathlib import Path
import os
import tempfile
import unittest

from quick_sender_core import Snapshot, StateStore, active_lines, next_item, read_text_file


class QuickSenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.email_file = self.folder / "邮箱.txt"
        self.words_file = self.folder / "话术.txt"
        self.email_file.write_text("a@example.com\nb@example.com\nc@example.com\n", encoding="utf-8")
        self.words_file.write_text("句子一\n句子二\n句子三\n", encoding="utf-8")
        self.store = StateStore(self.folder / "appdata")
        self.original = Snapshot(email_path=str(self.email_file), words_path=str(self.words_file),
                                 email_text="a@example.com\nb@example.com\nc@example.com\n",
                                 words_text="句子一\n句子二\n句子三\n")

    def test_two_cycle_and_persist_progress(self):
        self.store.save(self.original)
        item, advance = next_item(self.store.load())
        self.assertEqual(item, "a@example.com")
        self.store.save(advance)
        self.assertEqual(self.email_file.read_text(encoding="utf8"), "b@example.com\nc@example.com\n")
        recovered = StateStore(self.folder / "appdata").load()
        self.assertEqual(recovered.f4_state, 1)
        phrase, advanced = next_item(recovered)
        self.assertEqual(phrase, "句子一")
        self.store.save(advanced)
        recovered = self.store.load()
        self.assertEqual((recovered.f4_state, recovered.words_index), (0, 1))
        email, advanced = next_item(recovered)
        self.assertEqual(email, "b@example.com")
        self.store.save(advanced)
        phrase, advanced = next_item(self.store.load())
        self.assertEqual(phrase, "句子二")
        self.store.save(advanced)
        self.assertEqual(self.words_file.read_text(encoding="utf8"), "句子一\n句子二\n句子三\n")


    def test_original_email_txt_deletes_after_every_email_and_words_txt_never_changes(self):
        """防回归：逐次 F4 轮换时，直接核对用户导入的两个真实 TXT。"""
        original_words_bytes = self.words_file.read_bytes()
        state = self.store.save(self.original)
        pairs = [
            ("a@example.com", "b@example.com\nc@example.com\n", "句子一"),
            ("b@example.com", "c@example.com\n", "句子二"),
            ("c@example.com", "", "句子三"),
        ]
        for email, remainder, phrase in pairs:
            used_email, state = next_item(state)
            self.assertEqual(used_email, email)
            self.store.save(state)
            # 邮箱 F4 必须真实修改原始 TXT，不只是删除窗口里的文字。
            self.assertEqual(self.email_file.read_text(encoding="utf-8"), remainder)
            self.assertEqual(self.words_file.read_bytes(), original_words_bytes)
            used_phrase, state = next_item(self.store.load())
            self.assertEqual(used_phrase, phrase)
            self.store.save(state)
            # 话术 F4 不能更改原始话术文件（包括文件字节）。
            self.assertEqual(self.email_file.read_text(encoding="utf-8"), remainder)
            self.assertEqual(self.words_file.read_bytes(), original_words_bytes)
        restored = self.store.load()
        self.assertEqual(restored.words_index, 0)
        self.assertEqual(restored.f4_state, 0)
        self.assertEqual(active_lines(restored.email_text), [])

    def test_three_words_rotate_without_reset(self):
        s = self.original
        results = []
        for _ in range(6):
            item, s = next_item(s)
            results.append(item)
            self.store.save(s)
        self.assertEqual(results[:6], ["a@example.com", "句子一", "b@example.com", "句子二", "c@example.com", "句子三"])
        self.assertEqual(self.store.load().words_index, 0)

    def test_no_backup_files_created(self):
        state = self.store.save(self.original)
        for _ in range(4):
            _, state = next_item(state)
            self.store.save(state)
        self.assertFalse(list(self.folder.glob("*.QuickSender原始备份.txt")))
        self.assertFalse(list(self.folder.glob("*.tmp")))

    def test_manual_edits_saved_to_both_originals(self):
        self.store.save(self.original)
        mod = replace(self.original, email_text="custom@test.net\n", words_text="新的话术 🍀\n第二条\n", words_index=1)
        self.store.save(mod)
        self.assertEqual(self.email_file.read_text(encoding="utf8"), "custom@test.net\n")
        self.assertEqual(self.words_file.read_text(encoding="utf8"), "新的话术 🍀\n第二条\n")
        self.assertEqual(self.store.load().words_index, 1)

    def test_blank_lines_and_no_emails(self):
        s = replace(self.original, email_text="\n  \na@example.com \n\nb@example.com\n")
        value, new = next_item(s)
        self.assertEqual(value, "a@example.com")
        self.assertEqual(active_lines(new.email_text), ["b@example.com"])
        with self.assertRaises(ValueError):
            next_item(replace(s, email_text="\n "))

    def test_gbk_file_can_restore(self):
        text = "你好\n测试\n"
        self.words_file.write_bytes(text.encode("gbk"))
        result, encoding = read_text_file(str(self.words_file))
        self.assertEqual(result, text)
        self.assertEqual(encoding, "gb18030")
        state = replace(self.original, words_text=text, words_encoding=encoding)
        self.store.save(state)
        self.assertEqual(self.words_file.read_bytes(), text.replace("\n", os.linesep).encode("gb18030"))

    def test_gbk_new_emoji_roundtrips_without_loss(self):
        self.words_file.write_bytes("旧句子\n".encode("gb18030"))
        state = replace(self.original, words_text="新句子 🍀\n", words_encoding="gb18030")
        saved = self.store.save(state)
        self.assertIn(saved.words_encoding, ("utf-8-sig", "gb18030"))
        self.assertEqual(self.store.load().words_encoding, saved.words_encoding)
        self.assertEqual(read_text_file(str(self.words_file))[0], "新句子 🍀\n")

    def test_cannot_use_same_txt_for_both(self):
        with self.assertRaises(ValueError):
            self.store.save(replace(self.original, words_path=str(self.email_file)))

    def test_external_changes_detected(self):
        self.store.save(self.original)
        self.assertFalse(self.store.differing_files(self.original))
        self.email_file.write_text("手工换了一批邮箱\n", encoding="utf8")
        self.assertEqual(self.store.differing_files(self.original), [str(self.email_file)])


if __name__ == "__main__":
    unittest.main()
