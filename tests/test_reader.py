import codecs
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app import ReaderServer
from reader.archive import Archive, ROOT, seven_zip
from reader.book import Book, TextParser, TocParser, normalize
from reader.encoding import decode_text, system_encoding
from tests.fixtures import FIXTURES, fixture_files, generate, write_chm, write_lzx_chm


class EncodingTests(unittest.TestCase):
    def test_bom_precedes_meta_and_metadata(self):
        data = codecs.BOM_UTF8 + '<meta charset="big5">电脑𠀀'.encode('utf-8')
        text, encoding = decode_text(data, 'cp950')
        self.assertIn('电脑𠀀', text)
        self.assertEqual(encoding, 'utf-8-sig')
        for codec in ['utf-16', 'utf-32']:
            self.assertIn('电脑𠀀', decode_text('电脑𠀀'.encode(codec), 'cp950')[0])

    def test_meta_gb2312_and_gbk_use_gb18030(self):
        for declared in ['gb2312', 'gbk', 'cp936', 'gb18030']:
            with self.subTest(declared=declared):
                text, encoding = decode_text(('<meta charset="'+declared+'">电脑𠀀').encode('gb18030'), 'cp950')
                self.assertIn('电脑𠀀', text)
                self.assertEqual(encoding, 'gb18030')

    def test_http_equiv_and_big5(self):
        html = '<meta http-equiv="Content-Type" content="text/html; charset=big5">電腦'
        self.assertIn('電腦', decode_text(html.encode('cp950'), 'gb18030')[0])

    def test_css_charset_preserves_chinese_literals(self):
        data='@charset "UTF-8"; p::before{content:"電腦𠀀"}'.encode('utf-8')
        self.assertIn('電腦𠀀', decode_text(data, 'gb18030')[0])
        data='@charset "gbk"; p::before{content:"电脑"}'.encode('gbk')
        self.assertIn('电脑', decode_text(data, 'cp950')[0])

    def test_metadata_precedes_strict_utf8(self):
        data = '电脑'.encode('utf-8')
        self.assertEqual(decode_text(data, 'cp950')[1], 'cp950')
        self.assertEqual(decode_text(data, 'cp950', 'utf-8')[0], '电脑')

    def test_unmarked_utf8_page_in_big5_book(self):
        data = '<p>繁體與𠀀</p>'.encode('utf-8')
        self.assertEqual(decode_text(data, 'cp950', document=True), (data.decode(), 'utf-8'))

    def test_utf8_then_gb18030_fallback(self):
        for text, codec in [('電腦𠀀', 'utf-8'), ('电脑𠀀', 'gb18030')]:
            self.assertEqual(decode_text(text.encode(codec))[0], text)

    def test_manual_override_beats_bom_and_meta(self):
        data = '<meta charset="utf-8">電腦'.encode('cp950')
        self.assertIn('電腦', decode_text(data, 'gb18030', 'cp950')[0])

    def test_system_lcid_codepage_and_font(self):
        for number, expected in [(0x804,'gb18030'), (0x404,'cp950'), (936,'gb18030'), (65001,'utf-8')]:
            self.assertEqual(system_encoding({4: struct.pack('<I',number)},0), expected)
        self.assertEqual(system_encoding({16:b'SimSun,9,134'},0x404),'gb18030')
        self.assertEqual(system_encoding({},0x404),'cp950')

    def test_character_mapping_preserves_offsets(self):
        self.assertEqual(normalize('電腦與电脑 ABC𠀀'), normalize('电脑与電腦 abc𠀀'))
        self.assertEqual(len(normalize('電腦與电脑𠀀')), len('電腦與电脑𠀀'))


class BookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generate()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def book(self, path, encoding='auto'):
        book = Book(path, encoding)
        self.addCleanup(book.close)
        return book

    def test_five_real_chm_fixtures_and_bidirectional_search(self):
        for label in ['GB2312','GBK','GB18030','UTF-8','Big5']:
            with self.subTest(label=label):
                book = self.book(FIXTURES / ('測試 '+label+'.chm'))
                self.assertEqual(len(book.pages),2)
                self.assertEqual(book.toc[1]['path'],'/章節/中文 頁面.htm')
                self.assertEqual(book.toc[1]['depth'],1)
                traditional = book.search('電腦')
                simplified = book.search('电脑')
                self.assertEqual(traditional,simplified)
                self.assertEqual(traditional[0]['count'],3)
                self.assertNotIn('\ufffd',str(book.toc)+str(traditional)+book.title)
                if label == 'GB18030':
                    self.assertIn('𠀀',book.pages['/章節/中文 頁面.htm'].text)

    def test_independent_seven_zip_integrity_for_all_fixtures(self):
        self.assertIsNotNone(seven_zip(), '驗收環境需有既有 7-Zip')
        for path in FIXTURES.glob('*.chm'):
            with self.subTest(path=path.name):
                result = subprocess.run([seven_zip(),'t','-sccUTF-8',str(path)],capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout.decode('utf-8',errors='replace'))

    def test_lzx_and_legacy_gbk_directory_names(self):
        with patch('reader.archive.subprocess.run', wraps=subprocess.run) as run:
            book = self.book(FIXTURES / '測試 LZX GBK.chm')
            self.assertEqual(run.call_count, 1, '所有壓縮項目應由單次 7-Zip 執行解壓')
        self.assertTrue(any(e.section==1 for e in book.archive.raw.values()))
        self.assertEqual(book.toc[1]['path'],'/章節/中文 頁面.htm')
        self.assertEqual(book.search('電腦')[0]['count'],3)
        temporary = Path(book.archive._temporary.name)
        self.assertFalse(temporary.is_relative_to(ROOT), 'LZX 暫存應位於系統暫存目錄')
        book.close()
        self.assertFalse(temporary.exists())

    def test_existing_huffman_lzx_archive(self):
        path = Path(r'C:\Program Files\7-Zip\7-zip.chm')
        if not path.is_file():
            self.skipTest('此環境未安裝 7-Zip 說明 CHM')
        book = self.book(path)
        self.assertGreater(len(book.pages),20)
        self.assertTrue(book.search('archive'))

    def test_gbk_filenames_follow_lcid_and_manual_override(self):
        files = fixture_files('gbk', 'GBK')
        files['/目录.htm'] = '<meta charset="gbk"><body>目錄內容</body>'.encode('gbk')
        files['/toc.hhc'] = ('<ul><li><object type="text/sitemap"><param name="Name" value="目录頁">'
                             '<param name="Local" value="目录.htm"></object></ul>').encode('gbk')
        path = Path(self.temp.name) / 'gbk-names.chm'
        write_chm(path, files, name_encoding='gbk')
        auto = self.book(path)
        self.assertIn('/目录.htm', auto.pages)
        self.assertEqual(auto.toc[0]['path'], '/目录.htm')
        self.assertEqual(auto.resolve('目录.htm'), ('/目录.htm', ''))
        self.assertEqual(auto.resolve(quote('目录.htm'.encode('gbk'))), ('/目录.htm', ''))
        manual = self.book(path, 'gb18030')
        self.assertIn('/目录.htm', manual.pages)
        self.assertEqual(manual.toc[0]['path'], '/目录.htm')
        self.assertEqual(manual.resolve('目录.htm'), ('/目录.htm', ''))
        self.assertEqual(manual.resolve(quote('目录.htm'.encode('gbk'))), ('/目录.htm', ''))

    def test_raw_big5_names(self):
        path = Path(self.temp.name)/'中文 空白.chm'
        write_chm(path,fixture_files('cp950','Big5'),0x404,'cp950')
        book=self.book(path)
        self.assertEqual(book.toc[1]['path'],'/章節/中文 頁面.htm')

    def test_manual_content_encoding_preserves_utf8_directory_names(self):
        for codec, label, override in [('gbk','GBK','gb18030'),('cp950','Big5','cp950')]:
            with self.subTest(codec=codec):
                path = Path(self.temp.name) / (label + '.chm')
                write_chm(path, fixture_files(codec,label), 0x404 if codec=='cp950' else 0x804)
                auto, manual = self.book(path), self.book(path, override)
                self.assertEqual(manual.names, auto.names)
                self.assertEqual(manual.toc, auto.toc)
                self.assertEqual(manual.search('電腦'), auto.search('电脑'))
                self.assertEqual(manual.resolve('中文 頁面.htm', '/章節/other.htm'),
                                 ('/章節/中文 頁面.htm', ''))

    def test_manual_encoding_can_correct_legacy_directory_metadata(self):
        for lcid in (0x404,65001):
            with self.subTest(lcid=lcid):
                path = Path(self.temp.name) / ('wrong-lcid-'+str(lcid)+'.chm')
                files = fixture_files('gbk','GBK')
                del files['/#SYSTEM']  # 使用錯誤 header LCID，而非 fixture 的正確 #SYSTEM。
                write_chm(path, files, lcid, name_encoding='gbk')
                book = self.book(path, 'gb18030')
                self.assertIn('/章節/中文 頁面.htm', book.pages)
                self.assertEqual(book.toc[1]['path'], '/章節/中文 頁面.htm')

    def test_manual_legacy_name_that_is_also_valid_utf8(self):
        path = Path(self.temp.name) / 'ambiguous-name.chm'
        legacy = '绔犺妭'  # GBK bytes 同時是 UTF-8 的「章节」。
        files = fixture_files('gbk','GBK')
        files['/'+legacy+'/one.htm'] = '<meta charset="gbk"><a href="two.htm">下一頁</a>'.encode('gbk')
        files['/'+legacy+'/two.htm'] = '<meta charset="gbk"><body>第二頁</body>'.encode('gbk')
        files['/toc.hhc'] = ('<ul><object type="text/sitemap"><param name="Name" value="章節">'
                             '<param name="Local" value="'+legacy+'/one.htm"></object></ul>').encode('gbk')
        write_chm(path, files, name_encoding='gbk')
        book = self.book(path, 'gb18030')
        first = book.resolve(legacy+'/one.htm')[0]
        second = book.resolve(legacy+'/two.htm')[0]
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(book.toc[0]['path'], first)
        self.assertEqual(book.resolve('two.htm', first)[0], second)
        self.assertIn('/session/book/'+quote(second.lstrip('/')), book.render(first,'/session/').decode())

    def test_manual_gbk_content_with_utf8_percent_links(self):
        path = Path(self.temp.name) / 'utf8-links.chm'
        files = fixture_files('gbk','GBK')
        target = '/章節/中文 頁面.htm'
        files['/章節/入口.htm'] = ('<meta charset="gbk"><a href="'+quote('中文 頁面.htm')+'">下一頁</a>').encode('gbk')
        files['/toc.hhc'] = ('<ul><object type="text/sitemap"><param name="Name" value="中文頁面">'
                             '<param name="Local" value="'+quote(target)+'"></object></ul>').encode('gbk')
        write_chm(path, files)
        book = self.book(path, 'gb18030')
        self.assertEqual(book.toc[0]['path'], target)
        self.assertEqual(book.resolve(quote('中文 頁面.htm'), '/章節/入口.htm')[0], target)
        self.assertIn('/session/book/'+quote(target.lstrip('/')),
                      book.render('/章節/入口.htm','/session/').decode())

    def test_without_hhc_lists_all_html(self):
        files=fixture_files('gbk','GBK')
        del files['/toc.hhc']
        path=Path(self.temp.name)/'no-toc.chm'
        write_chm(path,files)
        book=self.book(path)
        self.assertEqual({n['path'] for n in book.toc},set(book.pages))

    def test_links_root_relative_backslash_case_and_percent(self):
        book=self.book(FIXTURES / '測試 GBK.chm')
        expected='/章節/中文 頁面.htm'
        for value in [expected,quote(expected),quote(expected.encode('gb18030')),expected.replace('/','\\')]:
            self.assertEqual(book.resolve(value,'/index.htm')[0],expected)
        self.assertEqual(book.resolve('../INDEX.HTM#back',expected),('/index.htm','back'))

    def test_text_excludes_script_style_and_decodes_entities(self):
        book=self.book(FIXTURES / '測試 GBK.chm')
        self.assertFalse(book.search('只有腳本'))
        self.assertFalse(book.search('只有樣式'))
        self.assertTrue(book.search('& 實體'))
        self.assertEqual(book.search('跨標籤：電腦')[0]['count'],1)

    def test_omitted_head_end_does_not_hide_body_text(self):
        parser = TextParser()
        parser.feed('<html><head><title>頁面標題</title><meta charset=gbk><body><p>可搜尋內文</p></body></html>')
        self.assertEqual(''.join(parser.parts), '可搜尋內文')
        self.assertEqual(''.join(parser.title_parts), '頁面標題')

    def test_toc_legacy_unclosed_li_and_group(self):
        parser=TocParser()
        parser.feed('<ul><li><object type="text/sitemap"><param name="Name" value="父層"></object>'
                    '<ul><li><object type="text/sitemap"><param name="Name" value="子層">'
                    '<param name="Local" value="a.htm"></object></ul></ul>')
        self.assertEqual([n['depth'] for n in parser.nodes],[0,1])

    def test_render_utf8_assets_and_removes_active_content(self):
        book=self.book(FIXTURES / '測試 GBK.chm')
        rendered=book.render('/章節/中文 頁面.htm','/session/').decode('utf-8')
        self.assertIn('电脑',rendered)
        self.assertIn('/session/book/'+quote('樣式.css'),rendered)
        self.assertIn('/session/book/'+quote('圖片.svg'),rendered)
        self.assertNotIn('<script',rendered)
        self.assertNotIn('charset=gb2312',rendered)

    def test_percent_encoded_chinese_anchors_in_html_and_hhc(self):
        for codec,label,lcid in [('gbk','GBK',0x804),('utf-8','UTF-8',65001),('cp950','Big5',0x404)]:
            for url_codec in ['utf-8',codec]:
                with self.subTest(codec=codec,url_codec=url_codec):
                    files=fixture_files(codec,label)
                    fragment=quote('中文錨點'.encode(url_codec))
                    files['/index.htm']=('<meta charset="'+codec+'"><body><a href="index.htm#'+fragment+'">跳至中文</a>'
                                         '<p id="中文錨點">中文定位</p></body>').encode(codec)
                    files['/toc.hhc']=('<meta charset="'+codec+'"><ul><li><object type="text/sitemap">'
                                       '<param name="Name" value="中文錨點"><param name="Local" value="index.htm#'+fragment+'">'
                                       '</object></ul>').encode(codec)
                    path=Path(self.temp.name)/'anchors.chm'
                    write_chm(path,files,lcid)
                    for override in ['auto', 'gb18030' if codec == 'gbk' else codec]:
                        with self.subTest(override=override):
                            book=self.book(path,override)
                            self.assertEqual(book.resolve('index.htm#'+fragment),('/index.htm','中文錨點'))
                            self.assertEqual(book.toc[0]['fragment'],'中文錨點')
                            rendered=book.render('/index.htm','/session/').decode('utf-8')
                            self.assertIn('#'+quote('中文錨點'),rendered)
                            self.assertNotIn('#%25',rendered)

    def test_object_and_iframe_fallback_text_stays_searchable_and_visible(self):
        files=fixture_files('gbk','GBK')
        files['/index.htm']=('<meta charset="gbk"><body>前文<object data="unsafe.ocx">物件替代文字</object>'
                             '<iframe src="other.htm">框架替代文字</iframe>後文</body>').encode('gbk')
        path=Path(self.temp.name)/'fallback.chm'
        write_chm(path,files)
        book=self.book(path)
        rendered=book.render('/index.htm','/session/').decode('utf-8')
        for text in ['物件替代文字','框架替代文字']:
            self.assertTrue(book.search(text))
            self.assertIn(text,rendered)
        self.assertNotIn('<object',rendered)
        self.assertNotIn('<iframe',rendered)
        self.assertNotIn('unsafe.ocx',rendered)

    def test_manual_ambiguous_percent_anchor_uses_existing_target(self):
        legacy = '璋曟郊'
        utf8 = legacy.encode('gbk').decode('utf-8')
        fragment = quote(legacy.encode('gbk'))
        for target, attr in [(legacy,'id'),(legacy,'name'),(utf8,'id')]:
            with self.subTest(target=target,attr=attr):
                files = fixture_files('gbk','GBK')
                files['/index.htm'] = ('<meta charset="gbk"><a href="index.htm#'+fragment+'">跳轉</a>'
                                       '<a '+attr+'="'+target+'">目標</a>').encode('gbk')
                files['/toc.hhc'] = ('<ul><object type="text/sitemap"><param name="Name" value="錨點">'
                                     '<param name="Local" value="index.htm#'+fragment+'"></object></ul>').encode('gbk')
                path = Path(self.temp.name) / ('anchor-'+attr+str(len(target))+'.chm')
                write_chm(path, files)
                book = self.book(path, 'gb18030')
                self.assertEqual(book.resolve('index.htm#'+fragment),('/index.htm',target))
                self.assertEqual(book.toc[0]['fragment'],target)
                self.assertIn('href="/session/book/index.htm#'+quote(target)+'"',
                              book.render('/index.htm','/session/').decode())

    def test_invalid_archive_rejected(self):
        path=Path(self.temp.name)/'壞掉.chm'
        path.write_bytes(b'not a chm')
        with self.assertRaises(ValueError):
            Book(path)
        data=bytearray((FIXTURES/'測試 GBK.chm').read_bytes())
        struct.pack_into('<Q',data,80,2**60)
        path.write_bytes(data)
        with self.assertRaises(ValueError):
            Book(path)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generate()

    def setUp(self):
        self.server=ReaderServer(FIXTURES/'測試 GBK.chm')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.server.close_book()

    def request(self, route, data=None, headers=None):
        request=Request(self.server.url+route, None if data is None else json.dumps(data).encode('utf-8'),
                        headers={'Content-Type':'application/json', **(headers or {})})
        return urlopen(request,timeout=10)

    def test_http_json_html_assets_and_search(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        with self.request('api/book') as response:
            self.assertEqual(json.load(response)['title'],'測試書籍 GBK')
        with self.request('api/search?q='+quote('電腦')) as response:
            results=json.loads(response.read().decode('utf-8'))
            self.assertIn('电脑',results[0]['snippet'])
        with self.request('book/'+quote('章節/中文 頁面.htm')) as response:
            self.assertIn('电脑',response.read().decode('utf-8'))
            self.assertIn('charset=utf-8',response.headers['Content-Type'])
            self.assertIn("script-src 'none'",response.headers['Content-Security-Policy'])
        for name,kind in [('樣式.css','text/css'),('圖片.svg','image/svg+xml')]:
            with self.request('book/'+quote(name)) as response:
                self.assertTrue(response.headers['Content-Type'].startswith(kind))

    def test_encoding_switch_reindexes(self):
        with self.request('api/encoding',{'encoding':'utf-8'}) as response:
            self.assertEqual(json.load(response)['encoding'],'utf-8')
        with self.request('api/encoding',{'encoding':'auto'}) as response:
            self.assertEqual(json.load(response)['encoding'],'auto')
        with self.request('api/search?q='+quote('電腦')) as response:
            self.assertEqual(json.load(response)[0]['count'],3)

    def test_font_size_default_save_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'prefs' / 'font-size.txt'
            with patch('app.font_size_file', return_value=settings):
                with self.request('api/font-size') as response:
                    self.assertEqual(json.load(response)['percent'], 100)
                self.assertFalse(settings.exists())
                with self.request('api/font-size', {'percent': 150}) as response:
                    self.assertEqual(json.load(response)['percent'], 150)
                for invalid in [0, '150', True]:
                    with self.assertRaises(HTTPError) as error:
                        self.request('api/font-size', {'percent': invalid})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                self.assertEqual(settings.read_text(), '150')
                settings.write_text('bad')
                with self.request('api/font-size') as response:
                    self.assertEqual(json.load(response)['percent'], 100)

    def test_text_spacing_default_save_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'prefs' / 'text-spacing.txt'
            with patch('app.text_spacing_file', return_value=settings):
                with self.request('api/text-spacing') as response:
                    payload = json.load(response)
                self.assertEqual(payload['percent'], 0)
                self.assertEqual(payload['choices'], [0, 5, 10, 15])
                self.assertFalse(settings.exists())
                with self.request('api/text-spacing', {'percent': 10}) as response:
                    self.assertEqual(json.load(response)['percent'], 10)
                for invalid in [-1, 20, '10', True]:
                    with self.assertRaises(HTTPError) as error:
                        self.request('api/text-spacing', {'percent': invalid})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                self.assertEqual(settings.read_text(), '10')
                settings.write_text('bad')
                with self.request('api/text-spacing') as response:
                    self.assertEqual(json.load(response)['percent'], 0)

    def test_font_family_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'font-family.txt'
            with patch('app.preference_file', return_value=settings):
                with self.request('api/font-family') as response:
                    self.assertEqual(json.load(response)['family'], 'original')
                self.assertFalse(settings.exists())
                with self.request('api/font-family', {'family': 'PMingLiU'}) as response:
                    self.assertEqual(json.load(response)['family'], 'PMingLiU')
                for invalid in ['unknown', True, ['PMingLiU']]:
                    with self.assertRaises(HTTPError) as error:
                        self.request('api/font-family', {'family': invalid})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                with self.request('api/font-family') as response:
                    self.assertEqual(json.load(response)['family'], 'PMingLiU')
                settings.write_text('unknown', encoding='ascii')
                with self.request('api/font-family') as response:
                    self.assertEqual(json.load(response)['family'], 'original')

    def test_line_height_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'line-height.txt'
            with patch('app.preference_file', return_value=settings):
                with self.request('api/line-height') as response:
                    self.assertEqual(json.load(response), {'percent': 0, 'choices': [0, 140, 160, 180, 200]})
                self.assertFalse(settings.exists())
                with self.request('api/line-height', {'percent': 160}) as response:
                    self.assertEqual(json.load(response)['percent'], 160)
                for invalid in [-1, 999, '160', 160.0, False]:
                    with self.assertRaises(HTTPError) as error:
                        self.request('api/line-height', {'percent': invalid})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                with self.request('api/line-height') as response:
                    self.assertEqual(json.load(response)['percent'], 160)
                settings.write_text('invalid', encoding='ascii')
                with self.request('api/line-height') as response:
                    self.assertEqual(json.load(response)['percent'], 0)

    def test_manual_encoding_preserves_browser_links_assets_and_search(self):
        with tempfile.TemporaryDirectory() as folder:
            for codec, label, override, lcid in [('gbk','GBK','gb18030',0x804),
                                                ('gb18030','GB18030','gb18030',0x804),
                                                ('cp950','Big5','cp950',0x404),
                                                ('utf-8','UTF-8','utf-8',65001)]:
                path = Path(folder) / (label + '.chm')
                writer = write_lzx_chm if codec == 'gbk' else write_chm
                writer(path, fixture_files(codec,label), lcid, name_encoding=codec)
                self.server.replace(path)
                expected_search = self.server.book.search('電腦')
                for encoding in [override, 'auto']:
                    with self.subTest(codec=codec, encoding=encoding):
                        with self.request('api/encoding', {'encoding':encoding}) as response:
                            metadata = json.load(response)
                        page = metadata['toc'][1]['path']
                        self.assertEqual(page, '/章節/中文 頁面.htm')
                        with self.request('book/'+quote(page.lstrip('/'))) as response:
                            rendered = response.read().decode('utf-8')
                        self.assertIn('歡迎閱讀 '+label, rendered)
                        for name, kind in [('樣式.css','text/css'),('圖片.svg','image/svg+xml')]:
                            self.assertIn(self.server.prefix+'book/'+quote(name), rendered)
                            with self.request('book/'+quote(name)) as response:
                                self.assertTrue(response.headers['Content-Type'].startswith(kind))
                        self.assertIn(self.server.prefix+'book/index.htm#back', rendered)
                        with self.request('book/index.htm') as response:
                            self.assertIn(self.server.prefix+'book/'+quote(page.lstrip('/')),
                                          response.read().decode('utf-8'))
                        for query in ['電腦','电脑']:
                            with self.request('api/search?q='+quote(query)) as response:
                                self.assertEqual(json.load(response), expected_search)

            # 現有 fixture 的 HTML 是 GBK，目錄檔名則是 UTF-8，與真實書相同。
            self.server.replace(FIXTURES/'測試 GBK.chm')
            with self.request('api/encoding', {'encoding':'gb18030'}) as response:
                page = json.load(response)['toc'][1]['path']
            self.assertEqual(page, '/章節/中文 頁面.htm')
            with self.request('book/'+quote(page.lstrip('/'))) as response:
                self.assertIn('歡迎閱讀 GBK', response.read().decode('utf-8'))

    def test_browser_path_is_decoded_once_without_reparsing_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            files = fixture_files('utf-8','UTF-8')
            pages = {'/literal%20name.htm':'literal-percent', '/literal name.htm':'space',
                     '/中文#章?節.htm':'reserved-characters'}
            for name, marker in pages.items():
                files[name] = ('<meta charset="utf-8"><body>'+marker+'</body>').encode('utf-8')
            path = Path(folder) / 'url-boundary.chm'
            write_chm(path, files, 65001)
            self.server.replace(path, 'utf-8')
            for name, marker in pages.items():
                with self.subTest(name=name):
                    with self.request('book/'+quote(name.lstrip('/'))) as response:
                        self.assertIn(marker, response.read().decode('utf-8'))

    def test_invalid_utf8_browser_path_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('book/%FF.htm')
        with caught.exception as response:
            self.assertEqual(response.code,400)

    def test_lzx_archive_cache_is_reused_when_switching_encoding(self):
        server = ReaderServer(FIXTURES / '測試 LZX GBK.chm')
        self.addCleanup(server.server_close)
        self.addCleanup(server.close_book)
        old = server.book
        archive = old.archive
        cache = archive._stream
        self.assertTrue(cache)
        server.replace(FIXTURES / '測試 LZX GBK.chm', 'gb18030')
        self.assertIs(server.book.archive, archive)
        self.assertIs(server.book.archive._stream, cache)
        self.assertFalse(old._owns_archive)
        self.assertTrue(server.book._owns_archive)

    def test_cancel_dialog_preserves_book(self):
        previous = self.server.metadata()
        previous_book = self.server.book
        result=[]
        def requester():
            with self.request('api/open',{}) as response:
                result.append(json.load(response))
        thread=threading.Thread(target=requester)
        thread.start()
        action,answer=self.server.actions.get(timeout=5)
        self.assertEqual(action,'pick')
        answer.put(('',None))
        thread.join(timeout=5)
        self.assertEqual(result[0],previous)
        self.assertIs(self.server.book,previous_book)

    def test_file_dialog_selection_opens_chinese_spaced_path(self):
        previous_revision = self.server.revision
        result=[]
        def requester():
            with self.request('api/open',{}) as response:
                result.append(json.load(response))
        thread=threading.Thread(target=requester)
        thread.start()
        action,answer=self.server.actions.get(timeout=5)
        self.assertEqual(action,'pick')
        answer.put((str(FIXTURES/'測試 UTF-8.chm'),None))
        thread.join(timeout=5)
        self.assertEqual(result[0]['title'],'測試書籍 UTF-8')
        self.assertEqual(result[0]['revision'],previous_revision+1)
        self.assertEqual(result[0]['toc'][1]['path'],'/章節/中文 頁面.htm')

    def test_unknown_session_and_cross_origin_post_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(f'http://127.0.0.1:{self.server.server_port}/',timeout=5)
        caught.exception.close()
        request=Request(self.server.url+'api/encoding',b'{}',headers={'Origin':'http://example.com'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request,timeout=5)
        caught.exception.close()

    def test_same_origin_posts_accept_full_origin(self):
        headers={'Origin':f'http://127.0.0.1:{self.server.server_port}',
                 'Sec-Fetch-Site':'same-origin'}
        with self.request('api/encoding',{'encoding':'auto'},headers) as response:
            self.assertEqual(json.load(response)['encoding'],'auto')

    def test_same_origin_chrome_posts_with_stripped_origin_port(self):
        # 系統預設 Chrome 實測：Origin 遺失 port，Fetch Metadata 仍為 same-origin。
        headers={'Origin':'http://127.0.0.1','Sec-Fetch-Site':'same-origin',
                 'Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'empty'}
        def choose(action):
            if action[0]=='pick':
                action[1].put((str(FIXTURES/'測試 GBK.chm'),None))
        with patch.object(self.server.actions,'put',side_effect=choose) as enqueue:
            for route,data in [('api/open',{}),('api/encoding',{'encoding':'auto'})]:
                with self.subTest(route=route):
                    with self.request(route,data,headers) as response:
                        self.assertEqual(response.status,200)
            self.assertEqual(enqueue.call_args_list[0].args[0][0],'pick')
        with self.request('api/exit',{},headers) as response:
            self.assertEqual(response.status,200)
        self.assertEqual(self.server.actions.get(timeout=5),('exit',None))

    def test_cross_origin_posts_remain_rejected(self):
        for origin in ['http://example.com','null',f'http://127.0.0.1:{self.server.server_port+1}']:
            with self.subTest(origin=origin):
                with self.assertRaises(HTTPError) as caught:
                    self.request('api/encoding',{'encoding':'auto'},
                                 {'Origin':origin,'Sec-Fetch-Site':'same-origin'})
                with caught.exception as response:
                    self.assertEqual(response.code,400)
                    self.assertEqual(json.load(response)['error'],'不接受其他網頁的操作請求。')

    def test_stripped_origin_requires_same_origin_fetch_metadata(self):
        for site in [None,'cross-site','same-site','none']:
            with self.subTest(site=site):
                headers={'Origin':'http://127.0.0.1'}
                if site is not None:
                    headers['Sec-Fetch-Site']=site
                with self.assertRaises(HTTPError) as caught:
                    self.request('api/encoding',{'encoding':'auto'},headers)
                with caught.exception as response:
                    self.assertEqual(response.code,400)
                    self.assertEqual(json.load(response)['error'],'不接受其他網頁的操作請求。')

    def test_foreign_host_rejected_even_with_same_origin_headers(self):
        for route in ['api/book','api/encoding','api/open','api/exit']:
            with self.subTest(route=route):
                with self.assertRaises(HTTPError) as caught:
                    self.request(route,None if route=='api/book' else {},
                                 {'Host':f'example.com:{self.server.server_port}',
                                  'Origin':'http://127.0.0.1','Sec-Fetch-Site':'same-origin'})
                with caught.exception as response:
                    self.assertEqual(response.code,400)
                    self.assertEqual(json.load(response)['error'],'只接受本機閱讀器的請求。')

    def test_failed_book_change_keeps_previous_book(self):
        with self.assertRaises(OSError):
            self.server.replace('missing.chm')
        self.assertEqual(self.server.book.title,'測試書籍 GBK')


if __name__ == '__main__':
    unittest.main()
