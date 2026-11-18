"""所有位元組轉文字均使用明確編碼。"""
import codecs
import re
import struct


def canonical(name):
    name = name.strip().lower().replace('_', '-')
    if name in {'gb2312', 'gbk', 'cp936', 'ms936', 'x-gbk', 'gb-2312', 'gb18030'}:
        return 'gb18030'
    if name in {'big5', 'big-5', 'cp950', 'windows-950', 'x-big5'}:
        return 'cp950'
    return codecs.lookup(name).name


def locale_encoding(lcid):
    if lcid in {4, 0x804, 0x1004, 936, 54936}:
        return 'gb18030'
    if lcid in {0x404, 0xc04, 0x1404, 950}:
        return 'cp950'
    if lcid == 65001:
        return 'utf-8'
    return None


def decode_text(data, hint=None, override='auto', *, document=False):
    codec = canonical(override) if override != 'auto' else None
    if codec is None:
        for bom, name in ((codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
                          (codecs.BOM_UTF8, 'utf-8-sig'), (codecs.BOM_UTF16_LE, 'utf-16'),
                          (codecs.BOM_UTF16_BE, 'utf-16')):
            if data.startswith(bom):
                codec = name
                break
        if codec is None:
            css = re.match(rb"""\s*@charset\s+["']([a-zA-Z0-9_.-]+)["']""", data[:256], re.I)
            if css:
                try:
                    codec = canonical(css[1].decode('ascii'))
                except LookupError:
                    pass
        if codec is None:
            for tag in re.findall(rb'<meta\b[^>]*>', data[:8192], re.I):
                match = re.search(rb"""charset\s*=\s*["'\s]*([a-zA-Z0-9_.-]+)""", tag, re.I)
                if match:
                    try:
                        codec = canonical(match[1].decode('ascii'))
                    except LookupError:
                        continue
                    break
        if document and codec is None and not data.isascii():
            # 個別 HTML 可採 UTF-8，即使書籍的 #SYSTEM 記錄是中文 ANSI。
            try:
                return data.decode('utf-8'), 'utf-8'
            except UnicodeDecodeError:
                pass
        codec = codec or hint
        if codec is None:
            try:
                return data.decode('utf-8', errors='strict'), 'utf-8'
            except UnicodeDecodeError:
                codec = 'gb18030'
    try:
        return data.decode(codec, errors='strict').lstrip('\ufeff'), codec
    except UnicodeDecodeError:
        if codec == 'cp950':
            try:
                return data.decode('big5hkscs', errors='strict'), 'big5hkscs'
            except UnicodeDecodeError:
                pass
        return data.decode(codec, errors='replace').lstrip('\ufeff'), codec


def system_records(data):
    records = {}
    offset = 4
    while offset + 4 <= len(data):
        kind, size = struct.unpack_from('<HH', data, offset)
        offset += 4
        if offset + size > len(data):
            raise ValueError('CHM 的 #SYSTEM 紀錄不完整。')
        records[kind] = data[offset:offset + size]
        offset += size
    return records


def system_encoding(records, header_lcid):
    record = records.get(4, b'')
    if len(record) >= 4:
        codec = locale_encoding(struct.unpack_from('<I', record)[0])
        if codec:
            return codec
    charset = records.get(16, b'').rstrip(b'\0').rsplit(b',', 1)[-1].strip()
    if charset in {b'134', b'136'}:
        return {b'134': 'gb18030', b'136': 'cp950'}[charset]
    return locale_encoding(header_lcid)
