"""ITSF/PMGL 原始檔名解析；LZX 使用本機既有 7-Zip 串流解壓。"""
from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

from .encoding import decode_text, system_records, system_encoding

ROOT = Path(__file__).resolve().parent.parent


def encint(value):
    parts = [value & 127]
    while value > 127:
        value >>= 7
        parts.append((value & 127) | 128)
    return bytes(reversed(parts))


def read_encint(data, offset, end):
    value = 0
    for _ in range(10):
        if offset >= end:
            break
        char = data[offset]
        offset += 1
        value = (value << 7) | (char & 127)
        if char < 128:
            return value, offset
    raise ValueError('CHM 目錄的可變長整數不完整。')


@dataclass(frozen=True)
class Entry:
    raw_name: bytes
    section: int
    offset: int
    size: int


def make_directory(entries, lcid=0x804):
    """ITSP v1 / PMGL 列表，包含 quick-reference 與項目數。"""
    groups, group, used = [], [], 20
    for entry in sorted(entries, key=lambda item: item.raw_name.lower()):
        record = (encint(len(entry.raw_name)) + entry.raw_name + encint(entry.section)
                  + encint(entry.offset) + encint(entry.size))
        if len(record) > 4000:
            raise ValueError('CHM 內部檔名過長。')
        if used + len(record) + 2 * ((len(group) + 1) // 5) + 2 > 4096:
            groups.append(group)
            group, used = [], 20
        group.append(record)
        used += len(record)
    groups.append(group)
    chunks = []
    for index, group in enumerate(groups):
        payload = b''.join(group)
        chunk = bytearray(4096)
        struct.pack_into('<4sIIii', chunk, 0, b'PMGL', 4096 - 20 - len(payload), 0,
                         index - 1, index + 1 if index + 1 < len(groups) else -1)
        chunk[20:20 + len(payload)] = payload
        offsets, position = [], 0
        for number, record in enumerate(group):
            if number and number % 5 == 0:
                offsets.append(position)
            position += len(record)
        for number, offset in enumerate(offsets):
            struct.pack_into('<H', chunk, 4092 - number * 2, offset)
        struct.pack_into('<H', chunk, 4094, len(group))
        chunks.append(chunk)
    header = bytearray(84)
    struct.pack_into('<4sIIIIIiiiIIII', header, 0, b'ITSP', 1, 84, 10, 4096, 2,
                     1, -1, 0, len(chunks) - 1, 0xffffffff, len(chunks), lcid)
    header[52:68] = uuid.UUID('5d02926a-212e-11d0-9df9-00a0c922e6ec').bytes_le
    struct.pack_into('<IIII', header, 68, 84, 0xffffffff, 0xffffffff, 0xffffffff)
    return bytes(header) + b''.join(chunks)


def wrap_archive(entries, content, lcid=0x804):
    """ITSF v3：fixture 與給 7-Zip 的 ASCII 檔名暫存副本。"""
    directory = make_directory(entries, lcid)
    data_offset = 96 + 24 + len(directory)
    header = bytearray(96)
    struct.pack_into('<4sIIIII', header, 0, b'ITSF', 3, 96, 1, 0, lcid)
    header[24:40] = uuid.UUID('7c01fd10-7baa-11d0-9e0c-00a0c922e6ec').bytes_le
    header[40:56] = uuid.UUID('7c01fd11-7baa-11d0-9e0c-00a0c922e6ec').bytes_le
    struct.pack_into('<QQQQQ', header, 56, 96, 24, 120, len(directory), data_offset)
    file_header = struct.pack('<IIQII', 0x1fe, 0, data_offset + len(content), 0, 0)
    return bytes(header) + file_header + directory + content


def decode_name(raw, hint, override='auto'):
    """Prefer locale bytes unless the UTF-8 candidate contains real CJK text."""
    localized, codec = decode_text(raw, hint, override)
    if override != 'auto':
        return localized, codec
    try:
        utf8 = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        return localized, codec
    if any(0x3400 <= ord(char) <= 0x9fff or 0x20000 <= ord(char) <= 0x323af
           for char in utf8):
        return utf8, 'utf-8'
    return localized, codec


def seven_zip():
    if getattr(sys, 'frozen', False):
        return str(ROOT / '7-Zip' / '7z.exe')
    for path in (Path(r'C:\Program Files\7-Zip\7z.exe'),
                 Path(r'C:\Program Files (x86)\7-Zip\7z.exe')):
        if path.is_file():
            return str(path)
    return shutil.which('7z')


class Archive:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.data = self.path.read_bytes()
        self._temporary = None
        self._stream = None
        try:
            self._parse()
            self.records = system_records(self.read_raw(b'/#SYSTEM')) if b'/#SYSTEM' in self.raw else {}
            self.hint = system_encoding(self.records, self.lcid)
        except BaseException:
            self.close()
            raise

    def _parse(self):
        data = self.data
        if len(data) < 96 or data[:4] != b'ITSF':
            raise ValueError('選取的檔案不是有效的 CHM。')
        version = struct.unpack_from('<I', data, 4)[0]
        if version not in {2, 3}:
            raise ValueError('僅支援 ITSF v2／v3 CHM。')
        self.lcid = struct.unpack_from('<I', data, 20)[0]
        directory, size = struct.unpack_from('<QQ', data, 72)
        self.content_offset = struct.unpack_from('<Q', data, 88)[0] if version == 3 else directory + size
        if directory + size > len(data) or size < 84 or self.content_offset > len(data):
            raise ValueError('CHM 區段超出檔案範圍。')
        if data[directory:directory + 4] != b'ITSP':
            raise ValueError('CHM 缺少 ITSP 目錄。')
        header_size = struct.unpack_from('<I', data, directory + 8)[0]
        block_size = struct.unpack_from('<I', data, directory + 16)[0]
        if header_size < 84 or block_size < 22 or header_size > size:
            raise ValueError('CHM 目錄區塊大小無效。')
        self.raw = {}
        for start in range(directory + header_size, directory + size, block_size):
            if start + block_size > directory + size:
                raise ValueError('CHM 目錄區塊不完整。')
            if data[start:start + 4] != b'PMGL':
                continue
            free = struct.unpack_from('<I', data, start + 4)[0]
            end = start + block_size - free
            if not start + 20 <= end <= start + block_size - 2:
                raise ValueError('CHM 目錄的可用空間無效。')
            pos = start + 20
            while pos < end:
                length, pos = read_encint(data, pos, end)
                if not length or pos + length > end:
                    raise ValueError('CHM 目錄檔名不完整。')
                name = data[pos:pos + length]
                pos += length
                values = []
                for _ in range(3):
                    value, pos = read_encint(data, pos, end)
                    values.append(value)
                entry = Entry(name, *values)
                if entry.section == 0 and self.content_offset + entry.offset + entry.size > len(data):
                    raise ValueError('CHM 項目內容超出檔案範圍。')
                self.raw[name] = entry

    def _prepare_compressed(self):
        tool = seven_zip()
        if not tool:
            raise ValueError('此 CHM 使用 LZX 壓縮，請先安裝 7-Zip（本程式不會下載執行檔）。')
        self._temporary = tempfile.TemporaryDirectory(prefix='chm-')
        self._aliased = Path(self._temporary.name) / 'book.chm'
        compressed = [entry for entry in self.raw.values() if entry.section == 1]
        self._stream_size = max(entry.offset + entry.size for entry in compressed)
        self._stream_name = '__chm_stream_' + uuid.uuid4().hex
        # 讓 7-Zip 一次輸出 LZX 位元組區段，依原始 offset 切回各檔，避免逐檔落地／讀回。
        entries = [entry for entry in self.raw.values() if entry.section != 1]
        entries.append(Entry(('/' + self._stream_name).encode('ascii'), 1, 0, self._stream_size))
        self._aliased.write_bytes(wrap_archive(entries, self.data[self.content_offset:], self.lcid))
        self._tool = tool

    def read_raw(self, name):
        entry = self.raw[name]
        if entry.section == 0:
            start = self.content_offset + entry.offset
            return self.data[start:start + entry.size]
        if entry.section != 1:
            raise ValueError('此 CHM 的壓縮格式不受支援。')
        if self._stream is None:
            if self._temporary is None:
                self._prepare_compressed()
            result = subprocess.run([self._tool, 'x', '-y', '-spd', '-so',
                                     str(self._aliased), self._stream_name],
                                    capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode != 0:
                detail = result.stderr.decode('utf-8', errors='replace').strip()
                raise ValueError('7-Zip 無法解壓 CHM：' + detail)
            if len(result.stdout) != self._stream_size:
                raise ValueError('7-Zip 無法完整解壓 CHM 壓縮區段。')
            self._stream = result.stdout
        return self._stream[entry.offset:entry.offset + entry.size]

    def names(self, override='auto'):
        names = {}
        for raw in self.raw:
            # CHM 的 UTF-8 目錄檔名獨立於 HTML 編碼；舊式檔名仍接受手動覆寫。
            name, codec = decode_name(raw, self.hint)
            if override != 'auto' and codec == 'utf-8':
                try:
                    raw.decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    codec = None
            if override != 'auto' and codec != 'utf-8':
                name, _ = decode_name(raw, self.hint, override)
            names[name] = raw
        return names

    def close(self):
        self._stream = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
