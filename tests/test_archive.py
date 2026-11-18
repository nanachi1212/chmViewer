import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from reader.archive import Archive, Entry, wrap_archive
from tests.fixtures import write_lzx_chm


class ArchiveStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '中文 空白.chm'
        self.files = {'/z-last.bin': b'0123456789', '/a-first.bin': b'abc', '/empty.bin': b''}
        write_lzx_chm(self.path, self.files)

    def rewrite_entries(self, extra):
        archive = Archive(self.path)
        try:
            self.path.write_bytes(wrap_archive(list(archive.raw.values()) + extra,
                                              archive.data[archive.content_offset:], archive.lcid))
        finally:
            archive.close()

    def test_stdout_bytes_preserve_offsets_gaps_overlap_and_empty_entries(self):
        self.rewrite_entries([Entry(b'/overlap.bin', 1, 3, 4), Entry(b'/gap.bin', 1, 20, 3)])
        expected = {**self.files, '/overlap.bin': b'3456', '/gap.bin': bytes(3)}
        archive = Archive(self.path)
        self.addCleanup(archive.close)
        with patch('reader.archive.subprocess.run', wraps=subprocess.run) as run:
            # 檔名字母順序不同於實際壓縮區段 offset 順序。
            for name in sorted(expected):
                self.assertEqual(archive.read_raw(name.encode()), expected[name])
            for name in reversed(sorted(expected)):
                self.assertEqual(archive.read_raw(name.encode()), expected[name])
            self.assertEqual(run.call_count, 1)
        temporary = Path(archive._temporary.name)
        self.assertEqual([p.name for p in temporary.iterdir()], ['book.chm'])
        archive.close()
        self.assertFalse(temporary.exists())

    def test_short_or_long_stdout_is_rejected_without_partial_cache(self):
        for output in (b'', bytes(14)):
            with self.subTest(length=len(output)):
                archive = Archive(self.path)
                try:
                    with patch('reader.archive.subprocess.run', return_value=SimpleNamespace(
                            returncode=0, stdout=output, stderr=b'')):
                        with self.assertRaisesRegex(ValueError, '無法完整解壓'):
                            archive.read_raw(b'/a-first.bin')
                    self.assertIsNone(archive._stream)
                finally:
                    archive.close()

    def test_entry_beyond_lzx_section_fails(self):
        # fixture 的實際 LZX 區段（含 padding）為 32768 bytes。
        self.rewrite_entries([Entry(b'/out-of-range.bin', 1, 32768, 1)])
        archive = Archive(self.path)
        self.addCleanup(archive.close)
        with self.assertRaisesRegex(ValueError, '無法解壓'):
            archive.read_raw(b'/out-of-range.bin')
        self.assertIsNone(archive._stream)


if __name__ == '__main__':
    unittest.main()
