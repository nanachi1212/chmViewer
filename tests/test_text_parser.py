"""索引快速路徑必須與同環境的標準 HTMLParser 保持一致。"""
from html.parser import HTMLParser
import unittest

from reader.book import TextParser


class StandardTextParser(TextParser):
    parse_starttag = HTMLParser.parse_starttag


class TextParserTests(unittest.TestCase):
    def test_text_and_title_match_standard_parser_including_chunked_input(self):
        cases = [
            '<html><head><title>中文 &amp; &#x20000;</title><body><p>內文</p>',
            '<P CLASS="MsoNormal" style="color:red; font-size:12pt">甲<span lang=zh>乙</span>丙',
            '<div a="1>0" b=\'a>b\' c disabled data-x="&amp; &#65;">文 &amp; &#65;</div>',
            '<p a="<b>">標籤字串</p><br/><img alt="不納入索引">尾',
            '<p a=x/><span/>尾',
            '<p a=x / ><b a===b>畸形</b><p a="x"b="y">無空白</p>',
            '<div a="unterminated>保留緩衝',
            '<script attr="&amp;"><p>不可索引</p></script><style>x<y</style>可索引',
            '<script/>後文<style/>末文<title/>非標題',
            '<title>甲<b>乙 &amp; 丙</title><textarea>a<b>&amp;</textarea>尾',
            '<iframe>替代<b>文字</b></iframe><object>物件替代</object>',
            '<xmp><p>&amp;</xmp><noembed>x</noembed><noframes>y</noframes>',
            '<noscript><p>可索引</p></noscript><plaintext>原樣<p>&amp;',
            '<svg><![CDATA[raw]]><title>SVG</title></svg><custom a=x>自訂</custom>',
            '<!-- <p>註解 --><?xml version="1.0"?><!DOCTYPE html><p>文</p>',
            '<p\tclass = "x"\r\nid=foo\fhidden >a&nbsp;b&#0;</p>',
            '<p>跨<span style="font-weight:bold">標</span>籤：電<span>腦</span>',
            '<p =oops>文字</p><p a=`x`>文字</p><p\vclass=x>垂直定位</p>',
            '<p/a=x>文</p><p a=x/y>文</p><p a=x//>文</p>',
        ]
        for source in cases:
            for chunk_size in (1, 7, len(source)):
                with self.subTest(source=source, chunk_size=chunk_size):
                    actual, expected = TextParser(), StandardTextParser()
                    for offset in range(0, len(source), chunk_size):
                        chunk = source[offset:offset + chunk_size]
                        actual.feed(chunk)
                        expected.feed(chunk)
                    for parser in (actual, expected):
                        parser.close()
                    self.assertEqual(actual.parts, expected.parts)
                    self.assertEqual(actual.title_parts, expected.title_parts)
                    self.assertEqual(actual.get_starttag_text(), expected.get_starttag_text())
                    self.assertEqual(actual.lasttag, expected.lasttag)


if __name__ == '__main__':
    unittest.main()
