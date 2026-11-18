"""執行：python app.py [書籍.chm]；開啟.cmd 可雙擊或接受拖放。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from reader.archive import ROOT
from reader.book import Book, CHARACTERS

HTML_TYPES = {'.htm', '.html', '.xhtml'}
FONT_SIZES = (75, 90, 100, 110, 125, 150, 175, 200)
TEXT_SPACINGS = (0, 5, 10, 15)
FONT_FAMILIES = ('original', 'Microsoft JhengHei', 'PMingLiU', 'DFKai-SB')
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
        # 隱藏的父視窗無法承接前景焦點；透明映射後讓原生對話框繼承。
        root.attributes('-alpha', 0.0)
        root.deiconify()
        root.update()
        root.lift()
        root.focus_force()
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            # HTTP 點擊由瀏覽器接收；短暫共用輸入焦點後立即解除。
            attached = foreground_thread != current_thread and user32.AttachThreadInput(
                current_thread, foreground_thread, True)
            try:
                user32.SetForegroundWindow(user32.GetAncestor(root.winfo_id(), 2))
                root.focus_force()
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
        return filedialog.askopenfilename(parent=root, title='開啟 CHM 電子書',
                                         filetypes=[('CHM 電子書', '*.chm')])
    finally:
        root.destroy()


def preference_file(name):
    folder = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(folder) / 'CHMViewer' / name


def font_size_file():
    return preference_file('font-size.txt')


def load_font_size():
    try:
        percent = int(font_size_file().read_text(encoding='ascii'))
    except (OSError, ValueError):
        return 100
    return percent if percent in FONT_SIZES else 100


def save_font_size(percent):
    if type(percent) is not int or percent not in FONT_SIZES:
        raise ValueError('不支援此內文字級。')
    write_preference(font_size_file(), str(percent))


def write_preference(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        name = Path(temporary.name)
    try:
        name.write_text(value, encoding='ascii')
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def text_spacing_file():
    return preference_file('text-spacing.txt')


def load_text_spacing():
    try:
        spacing = int(text_spacing_file().read_text(encoding='ascii'))
    except (OSError, ValueError):
        return 0
    return spacing if spacing in TEXT_SPACINGS else 0


def save_text_spacing(spacing):
    if type(spacing) is not int or spacing not in TEXT_SPACINGS:
        raise ValueError('不支援此文字間距。')
    write_preference(text_spacing_file(), str(spacing))


def load_font_family():
    try:
        family = preference_file('font-family.txt').read_text(encoding='ascii').strip()
    except (OSError, ValueError):
        return 'original'
    return family if family in FONT_FAMILIES else 'original'


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
                elif route == 'api/font-size':
                    self.send({'percent': load_font_size(), 'choices': FONT_SIZES})
                elif route == 'api/text-spacing':
                    self.send({'percent': load_text_spacing(), 'choices': TEXT_SPACINGS})
                elif route == 'api/font-family':
                    self.send({'family': load_font_family(), 'choices': FONT_FAMILIES})
                elif route == 'api/characters':
                    self.send({chr(key): value for key, value in CHARACTERS.items()})
                elif route == 'api/search':
                    self.send(server.book.search(query.get('q', [''])[0]) if server.book else [])
                elif route.startswith('book/') and server.book:
                    # 閱讀器產生的 URL 固定是 UTF-8，不能再套用原書的手動編碼。
                    path = unquote('/' + route[5:], encoding='utf-8', errors='strict')
                    name = server.book.lookup.get(server.book.key(path))
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
            # Origin 不含 port 時，另以同源 Fetch Metadata 驗證。
            stripped_same_origin = (origin == 'http://127.0.0.1'
                                    and self.headers.get('Sec-Fetch-Site') == 'same-origin')
            if origin and origin != f'http://127.0.0.1:{server.server_port}' and not stripped_same_origin:
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
            elif route == 'api/font-size':
                percent = data.get('percent') if isinstance(data, dict) else None
                save_font_size(percent)
                self.send({'percent': percent})
            elif route == 'api/text-spacing':
                spacing = data.get('percent') if isinstance(data, dict) else None
                save_text_spacing(spacing)
                self.send({'percent': spacing})
            elif route == 'api/font-family':
                family = data.get('family') if isinstance(data, dict) else None
                if family not in FONT_FAMILIES:
                    raise ValueError('不支援此內文字體。')
                write_preference(preference_file('font-family.txt'), family)
                self.send({'family': family})
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
    window = None
    try:
        if sys.stdout is not None:
            print('閱讀器已啟動：' + server.url, flush=True)
        if args.ready_file:
            Path(args.ready_file).write_text(json.dumps({'url': server.url, 'port': server.server_port, 'pid': os.getpid()},
                                                       ensure_ascii=False), encoding='utf-8')
        if not args.no_browser:
            if os.name == 'nt':
                from reader.window import ReaderWindow, host_path
                host = host_path()
                if host.is_file():
                    window = ReaderWindow(host, server.url)
            if window is None and not webbrowser.open(server.url):
                from tkinter import messagebox
                messagebox.showinfo('CHM 閱讀器', '請在瀏覽器開啟本機網址：\n' + server.url)
        while window is None or not window.closed():
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
        if window is not None:
            window.close()


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
        if sys.stderr is not None:
            print('啟動失敗：' + str(error), file=sys.stderr, flush=True)
        elif not args.no_browser:
            from tkinter import messagebox
            messagebox.showerror('CHM 閱讀器', '啟動失敗：' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
