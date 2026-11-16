"""目錄、站內路徑、純文字全文索引與 UTF-8 頁面。"""
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from urllib.parse import quote, unquote_to_bytes, urlsplit

from .archive import Archive, ROOT, decode_name
from .encoding import decode_text


def character_map():
    result = {}
    for line in (ROOT / 'vendor' / 'TSCharacters.txt').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        key, values = line.split('\t', 1)
        target = values.split()[0]
        if len(key) == len(target) == 1:
            result[ord(key)] = target
    result.update({ord(chr(n)): chr(n + 32) for n in range(65, 91)})
    return result


CHARACTERS = character_map()


def normalize(text):
    return text.translate(CHARACTERS)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title_parts = [], []
        self.excluded = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.excluded += 1
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.excluded = max(0, self.excluded - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if not self.excluded and not self.in_title:
            self.parts.append(data)


class TocParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.depth = -1
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'ul':
            self.depth += 1
        if tag == 'object' and attrs.get('type', '').lower() == 'text/sitemap':
            self.current = {}
        if tag == 'param' and self.current is not None:
            self.current[attrs.get('name', '').lower()] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'ul':
            self.depth = max(-1, self.depth - 1)
        if tag == 'object' and self.current is not None:
            if self.current.get('name'):
                self.nodes.append({'title': self.current['name'], 'local': self.current.get('local', ''),
                                   'depth': max(0, self.depth)})
            self.current = None


@dataclass
class Page:
    html: str
    title: str
    text: str
    normalized: str
    encoding: str


class Book:
    def __init__(self, path, override='auto', archive=None):
        self.archive = archive or Archive(path)
        self._owns_archive = archive is None
        try:
            self.override = override
            self.names = self.archive.names(override)
            self.lookup = {self.key(name): name for name in self.names}
            if override == 'auto':
                for name, raw in self.names.items():
                    try:
                        utf8_name = raw.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        continue
                    self.lookup.setdefault(self.key(utf8_name), name)
            self.pages = {}
            for name in self.names:
                if name.lower().endswith(('.htm', '.html', '.xhtml')):
                    html, codec = self.decode(name)
                    parser = TextParser()
                    parser.feed(html)
                    text = ''.join(parser.parts)
                    title = ''.join(parser.title_parts).strip() or posixpath.basename(name)
                    self.pages[name] = Page(html, title, text, normalize(text), codec)
            if not self.pages:
                raise ValueError('此 CHM 沒有可閱讀的 HTML 頁面。')
            title_data = self.archive.records.get(3, b'').rstrip(b'\0')
            self.title = decode_text(title_data, self.archive.hint, override)[0] if title_data else Path(path).stem
            self.toc = self._toc()
            home_data = self.archive.records.get(2, b'').rstrip(b'\0')
            home = decode_text(home_data, self.archive.hint, override)[0] if home_data else ''
            self.home = self.resolve(home)[0] if home else next(iter(self.pages))
            if self.home not in self.pages:
                self.home = next(iter(self.pages))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def key(name):
        return posixpath.normpath('/' + name.replace('\\', '/').lstrip('/')).casefold()

    def decode(self, name):
        return decode_text(self.archive.read_raw(self.names[name]), self.archive.hint, self.override)

    def resolve(self, value, base='/'):
        value = value.replace('\\', '/')
        if '::' in value:
            value = value.split('::', 1)[1]
        split = urlsplit(value)
        def component(value):
            if '%' not in value:
                return value
            raw = unquote_to_bytes(value)
            return decode_name(raw, self.archive.hint, self.override)[0]
        fragment = component(split.fragment)
        if split.scheme or split.netloc:
            return None, fragment
        # 中文路徑與錨點都只解碼一次，輸出時再統一採 UTF-8 URL 編碼。
        decoded = component(split.path)
        if not decoded:
            decoded = base
        elif not decoded.startswith('/'):
            decoded = posixpath.join(posixpath.dirname(base), decoded)
        return self.lookup.get(self.key(decoded)), fragment

    def url(self, value, base, prefix):
        name, fragment = self.resolve(value, base)
        if name is None:
            if urlsplit(value).scheme.lower() in {'http', 'https', 'data', 'mailto'}:
                return value
            return '#'
        return prefix + 'book/' + quote(name.lstrip('/'), safe='/') + ('#' + quote(fragment) if fragment else '')

    def _toc(self):
        data = self.archive.records.get(0, b'').rstrip(b'\0')
        name = self.resolve(decode_text(data, self.archive.hint, self.override)[0])[0] if data else None
        if not name:
            name = next((name for name in self.names if name.lower().endswith('.hhc')), None)
        nodes = []
        if name:
            parser = TocParser()
            parser.feed(self.decode(name)[0])
            for node in parser.nodes:
                local = node.pop('local')
                path, fragment = self.resolve(local, name) if local else (None, '')
                node.update(path=path, fragment=fragment)
                nodes.append(node)
        return nodes or [{'title': page.title, 'path': name, 'fragment': '', 'depth': 0}
                         for name, page in self.pages.items()]

    def search(self, query):
        needle = normalize(query.strip())
        if not needle:
            return []
        results = []
        for name, page in self.pages.items():
            start, offsets = 0, []
            while (start := page.normalized.find(needle, start)) >= 0:
                offsets.append(start)
                start += max(1, len(needle))
            if offsets:
                offset = offsets[0]
                results.append({'path': name, 'title': page.title, 'count': len(offsets),
                                'offset': offset, 'length': len(needle),
                                'snippet': page.text[max(0, offset - 35):offset + len(needle) + 65]})
        return results

    def css(self, text, name, prefix):
        def replace(match):
            value = match[2].strip()
            return 'url("' + self.url(value, name, prefix).replace('"', '%22') + '")'
        text = re.sub(r"""url\(\s*(["']?)(.*?)\1\s*\)""", replace, text, flags=re.I)
        return re.sub(r"""(@import\s+)(["'])(.*?)\2""",
                      lambda m: m[1] + '"' + self.url(m[3], name, prefix) + '"', text, flags=re.I)

    def render(self, name, prefix):
        renderer = Renderer(self, name, prefix)
        renderer.feed(self.pages[name].html)
        return ('<!doctype html><html><head><meta charset="utf-8">'
                '<style>mark[data-chm-hit]{background:#ffdf7a!important;color:#191919!important}</style>'
                '</head><body>' + ''.join(renderer.output) + '</body></html>').encode('utf-8')

    def close(self):
        if self._owns_archive:
            self.archive.close()


class Renderer(HTMLParser):
    """保留靜態 HTML/CSS，移除執行程式及會覆寫 UTF-8 的舊式宣告。"""
    def __init__(self, book, name, prefix):
        super().__init__(convert_charrefs=False)
        self.book, self.name, self.prefix = book, name, prefix
        self.output = []
        self.skip = 0
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.skip += 1
        if self.skip or tag in {'html', 'head', 'body', 'meta', 'base', 'embed', 'object', 'iframe', 'param'}:
            return
        attrs = dict(attrs)
        self.in_style = tag == 'style' or self.in_style
        for attr in list(attrs):
            value = attrs[attr]
            if attr.startswith('on') or attr in {'srcdoc', 'action', 'formaction', 'srcset'}:
                del attrs[attr]
            elif value is not None and attr in {'href', 'src', 'background', 'poster'}:
                attrs[attr] = self.book.url(value, self.name, self.prefix)
            elif attr == 'style' and value:
                attrs[attr] = self.book.css(value, self.name, self.prefix)
        self.output.append('<' + tag + ''.join(' ' + k + ('="' + escape(v, quote=True) + '"' if v is not None else '')
                                               for k, v in attrs.items()) + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in {'html', 'head', 'body', 'meta', 'base', 'embed', 'object', 'iframe', 'param'}:
            return
        if tag == 'style':
            self.in_style = False
        self.output.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.skip:
            self.output.append(self.book.css(data, self.name, self.prefix) if self.in_style else data)

    def handle_entityref(self, name):
        if not self.skip:
            self.output.append('&' + name + ';')

    def handle_charref(self, name):
        if not self.skip:
            self.output.append('&#' + name + ';')
