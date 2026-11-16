"""執行：python app.py [書籍.chm]；開啟.cmd 可雙擊或接受拖放。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from reader.archive import ROOT
from reader.book import Book, CHARACTERS

HTML_TYPES = {'.htm', '.html', '.xhtml'}
TYPES = {'.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.gif': 'image/gif', '.svg': 'image/svg+xml', '.bmp': 'image/bmp', '.ico': 'image/x-icon',
         '.webp': 'image/webp', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf'}


def choose_file():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        return filedialog.askopenfilename(parent=root, title='開啟 CHM 電子書',
                                         filetypes=[('CHM 電子書', '*.chm')])
    finally:
        root.destroy()


class ReaderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path=None, picker=choose_file):
        self.book = Book(path) if path else None
        self.lock = threading.RLock()
        self.actions = queue.Queue()
        self.picker = picker
        self.prefix = '/' + secrets.token_urlsafe(24) + '/'
        self.revision = 0
        super().__init__(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server_port}' + self.prefix

    def metadata(self):
        if not self.book:
            return {'title': '尚未開啟電子書', 'toc': [], 'home': '', 'encoding': 'auto', 'pages': 0,
                    'revision': self.revision}
        return {'title': self.book.title, 'toc': self.book.toc, 'home': self.book.home,
                'encoding': self.book.override, 'pages': len(self.book.pages), 'revision': self.revision}

    def replace(self, path, encoding='auto'):
        old = self.book
        resolved = Path(path).resolve()
        reuse = old.archive if old and old.archive.path == resolved else None
        book = Book(path, encoding, reuse)
        if reuse:
            old._owns_archive = False
            book._owns_archive = True
        self.book = book
        self.revision += 1
        if old:
            old.close()

    def close_book(self):
        if self.book:
            self.book.close()
            self.book = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, kind='application/json; charset=utf-8', status=200, book=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if book:
            self.send_header('Content-Security-Policy',
                             "default-src 'self' data:; script-src 'none'; style-src 'self' 'unsafe-inline'; "
                             "object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        parsed = urlsplit(self.path)
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            raise ValueError('只接受本機閱讀器的請求。')
        if not parsed.path.startswith(self.server.prefix):
            raise FileNotFoundError('找不到此閱讀器工作階段。')
        return parsed.path[len(self.server.prefix):], parse_qs(parsed.query, encoding='utf-8', errors='strict')

    def do_GET(self):
        server = self.server
        try:
            route, query = self.route()
            with server.lock:
                if route == '':
                    self.send((ROOT / 'reader' / 'ui.html').read_bytes(), 'text/html; charset=utf-8')
                elif route == 'api/book':
                    self.send(server.metadata())
                elif route == 'api/characters':
                    self.send({chr(key): value for key, value in CHARACTERS.items()})
                elif route == 'api/search':
                    self.send(server.book.search(query.get('q', [''])[0]) if server.book else [])
                elif route.startswith('book/') and server.book:
                    name = server.book.resolve('/' + route[5:])[0]
                    if name is None:
                        raise FileNotFoundError('CHM 內找不到此頁面或資源。')
                    suffix = Path(name).suffix.lower()
                    if suffix in HTML_TYPES:
                        body = server.book.render(name, server.prefix)
                        self.send(body, 'text/html; charset=utf-8', book=True)
                    elif suffix == '.css':
                        css = server.book.css(server.book.decode(name)[0], name, server.prefix)
                        self.send(css.encode('utf-8'), 'text/css; charset=utf-8', book=True)
                    else:
                        self.send(server.book.archive.read_raw(server.book.names[name]),
                                  TYPES.get(suffix, 'application/octet-stream'), book=True)
                else:
                    raise FileNotFoundError('找不到頁面。')
        except (ValueError, OSError, KeyError) as error:
            self.send({'error': str(error)}, status=404 if isinstance(error, FileNotFoundError) else 400)

    def do_POST(self):
        server = self.server
        try:
            route, _ = self.route()
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{server.server_port}':
                raise ValueError('不接受其他網頁的操作請求。')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 8192:
                raise ValueError('請求內容過長。')
            data = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
            if route == 'api/open':
                answer = queue.Queue(maxsize=1)
                server.actions.put(('pick', answer))
                path, error = answer.get(timeout=600)
                if error:
                    raise ValueError(error)
                with server.lock:
                    if path:
                        server.replace(path)
                    self.send(server.metadata())
            elif route == 'api/encoding':
                encoding = data.get('encoding')
                if encoding not in {'auto', 'gb18030', 'utf-8', 'cp950'}:
                    raise ValueError('不支援此編碼選項。')
                with server.lock:
                    if server.book:
                        server.replace(server.book.archive.path, encoding)
                    self.send(server.metadata())
            elif route == 'api/exit':
                self.send({'message': '閱讀器已關閉。'})
                server.actions.put(('exit', None))
            else:
                raise ValueError('不支援此操作。')
        except (ValueError, OSError, KeyError, queue.Empty) as error:
            self.send({'error': str(error) or '檔案選擇等待逾時。'}, status=400)


def run(args):
    server = ReaderServer(args.path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print('閱讀器已啟動：' + server.url, flush=True)
        if args.ready_file:
            Path(args.ready_file).write_text(json.dumps({'url': server.url, 'port': server.server_port, 'pid': os.getpid()},
                                                       ensure_ascii=False), encoding='utf-8')
        if not args.no_browser:
            if not webbrowser.open(server.url):
                print('無法自動開啟瀏覽器，請開啟上方網址。', flush=True)
        while True:
            try:
                action, answer = server.actions.get(timeout=0.2)
            except queue.Empty:
                continue
            if action == 'exit':
                break
            if action == 'pick':
                try:
                    answer.put((server.picker(), None))
                except Exception as error:
                    answer.put(('', '無法開啟檔案對話框：' + str(error)))
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        server.close_book()


def main():
    parser = argparse.ArgumentParser(description='支援繁簡搜尋的 CHM 閱讀器')
    parser.add_argument('path', nargs='?', help='CHM 檔案路徑')
    parser.add_argument('--no-browser', action='store_true', help='驗證用：不自動開啟瀏覽器')
    parser.add_argument('--ready-file', help='驗證用：將本機網址寫入 JSON 檔')
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except Exception as error:
        print('啟動失敗：' + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
