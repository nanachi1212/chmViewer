"""可重現的真實 ITSF v3 Section 0 CHM，無需 hhc.exe。"""
from pathlib import Path
import struct
from reader.archive import Entry, wrap_archive

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def write_chm(path, files, lcid=0x804, name_encoding='utf-8'):
    files = {'::DataSpace/NameList': struct.pack('<HHH', 16, 1, 12) + 'Uncompressed'.encode('utf-16-le') + bytes(2), **files}
    entries, content = [], bytearray()
    for name, data in files.items():
        entries.append(Entry(name.encode(name_encoding), 0, len(content), len(data)))
        content.extend(data)
    Path(path).write_bytes(wrap_archive(entries, bytes(content), lcid))


def fixture_files(codec, label):
    traditional = codec == 'cp950'
    word = '電腦' if traditional else '电脑'
    title = '電腦與程式設計' if traditional else '电脑与程序设计'
    extra = '𠀀' if codec == 'gb18030' else ''
    local = '章節/中文 頁面.htm'
    charset = {'gb2312': 'gb2312', 'gbk': 'gb2312', 'gb18030': 'gbk', 'cp950': 'big5', 'utf-8': 'utf-8'}[codec]
    html = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset='+charset+'">'
            '<title>'+title+'</title><link rel="stylesheet" href="../樣式.css"></head><body>'
            '<h1>'+title+'</h1><p>歡迎閱讀 '+label+'。</p>'
            '<div style="height:1000px"></div><p id="hit">測試：'+word+'，'+extra+'；'
            '跨標籤：'+word[0]+'<b>'+word[1]+'</b>。&amp; 實體。</p>'
            '<img src="../圖片.svg" alt="測試圖片"><a href="../index.htm#back">返回首頁</a>'
            '<script>只有腳本不能搜尋</script><style>.hidden{--text:"只有樣式不能搜尋"}</style>'
            '</body></html>')
    toc = ('<html><head><meta charset="'+charset+'"></head><body><ul>'
           '<li><object type="text/sitemap"><param name="Name" value="測試目錄 '+label+'">'
           '<param name="Local" value="index.htm"></object><ul>'
           '<li><object type="text/sitemap"><param name="Name" value="'+title+' '+extra+'">'
           '<param name="Local" value="'+local+'"></object></ul></ul></body></html>')
    home = ('<html><head><meta charset="'+charset+'"><title>測試首頁 '+label+'</title></head>'
            '<body><h1 id="back">測試首頁 '+label+'</h1><a href="'+local+'">開啟中文頁面</a>'
            '<a href="/'+local+'">根目錄連結</a></body></html>')
    book_title = ('测试书籍 ' if codec == 'gb2312' else '測試書籍 ') + label
    records = {0: b'toc.hhc\0', 2: b'index.htm\0', 3: book_title.encode(codec)+b'\0',
               4: struct.pack('<I', 0x404 if traditional else (65001 if codec == 'utf-8' else 0x804))+bytes(24)}
    system = struct.pack('<I', 3)+b''.join(struct.pack('<HH', kind, len(data))+data for kind,data in records.items())
    return {'/#SYSTEM': system, '/toc.hhc': toc.encode(codec, 'xmlcharrefreplace'),
            '/index.htm': home.encode(codec, 'xmlcharrefreplace'),
            '/'+local: html.encode(codec, 'xmlcharrefreplace'), '/樣式.css': '@charset "UTF-8"; body{color:rgb(31,61,46);font-size:20px}'.encode('utf-8'),
            '/圖片.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="50"><rect width="80" height="50" fill="#738e79"/></svg>'.encode('utf-8')}


def write_lzx_chm(path, files, lcid=0x804, name_encoding='utf-8'):
    """單一 LZX type-3 區塊，驗證真實 Section 1 與 GBK 原始檔名。"""
    plain, entries = bytearray(), []
    for name, data in files.items():
        entries.append(Entry(name.encode(name_encoding), 1, len(plain), len(data)))
        plain.extend(data)
    if len(plain) >= 32768:
        raise ValueError('測試 LZX 寫入器僅支援一個小區塊。')
    plain.extend(bytes(32768 - len(plain)))
    bits = (3 << 28) | (len(plain) << 4)
    compressed = struct.pack('<HHIII', bits >> 16, bits & 0xffff, 1, 1, 1) + plain
    if len(compressed) % 2:
        compressed += bytes(1)
    names = ['Uncompressed', 'MSCompressed']
    namelist = struct.pack('<H', 2) + b''.join(struct.pack('<H',len(n))+n.encode('utf-16-le')+bytes(2) for n in names)
    namelist = struct.pack('<H', (len(namelist)+2)//2) + namelist
    prefix = '::DataSpace/Storage/MSCompressed/'
    metadata = {'::DataSpace/NameList': namelist,
                prefix+'ControlData': struct.pack('<I4sIIII', 5, b'LZXC', 2, 2, 2, 1),
                prefix+'SpanInfo': struct.pack('<Q', len(plain)),
                prefix+'Transform/{7FC28940-9D31-11D0-9B27-00A0C91E9C7C}/InstanceData/ResetTable':
                    struct.pack('<IIIIQQQQQ', 2, 2, 8, 40, len(plain), len(compressed), 32768, 0, len(compressed)),
                prefix+'Content': compressed}
    content = bytearray()
    for name, data in metadata.items():
        entries.append(Entry(name.encode('ascii'), 0, len(content), len(data)))
        content.extend(data)
    Path(path).write_bytes(wrap_archive(entries, bytes(content), lcid))


def generate():
    FIXTURES.mkdir(exist_ok=True)
    for codec,label in [('gb2312','GB2312'),('gbk','GBK'),('gb18030','GB18030'),('utf-8','UTF-8'),('cp950','Big5')]:
        write_chm(FIXTURES / ('測試 '+label+'.chm'), fixture_files(codec,label),
                  0x404 if codec == 'cp950' else (65001 if codec == 'utf-8' else 0x804))


    write_lzx_chm(FIXTURES / '測試 LZX GBK.chm', fixture_files('gbk', 'LZX GBK'), name_encoding='gb18030')


if __name__ == '__main__':
    generate()
