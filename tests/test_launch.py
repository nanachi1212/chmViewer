"""使用真正的 開啟.cmd，在 ACP 950 下依序啟動全部 fixture 並保存 HTTP 證據。"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.parse import quote
from urllib.request import Request, urlopen

from reader.archive import ROOT
from tests.fixtures import FIXTURES, generate


def cmd_line(*args):
    # cmd /s /c 會移除最外層的一對引號，裡面的路徑仍要各自加引號。
    command = subprocess.list2cmdline([str(ROOT/'開啟.cmd'), *map(str, args)])
    return f'"{os.environ.get("COMSPEC","cmd.exe")}" /d /s /c "{command}"'


def launch(fixture, ready):
    return subprocess.Popen(cmd_line(fixture,'--no-browser','--ready-file',ready),
                            cwd=ROOT.parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def await_ready(process, ready):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if ready.exists():
            try:
                return json.loads(ready.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                pass
        if process.poll() is not None:
            raise AssertionError(process.communicate()[0].decode('utf-8',errors='replace'))
        time.sleep(0.05)
    raise AssertionError('開啟.cmd 啟動逾時')


def stop(process, ready_info):
    if ready_info:
        try:
            with urlopen(Request(ready_info['url']+'api/exit',b'{}',
                                 headers={'Content-Type':'application/json'}),timeout=5) as response:
                response.read()
        except OSError:
            pass
    try:
        output=process.communicate(timeout=8)[0]
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        output=process.communicate(timeout=5)[0]
        raise AssertionError('閱讀器無法正常關閉：'+output.decode('utf-8',errors='replace'))
    return output


@unittest.skipUnless(os.name=='nt','此項驗證 Windows CMD 啟動入口')
class LauncherTests(unittest.TestCase):
    def test_file_dialog_opens_in_foreground(self):
        from ctypes import wintypes
        import sys
        user32=ctypes.windll.user32
        user32.GetForegroundWindow.restype=wintypes.HWND
        if not user32.GetForegroundWindow():
            self.skipTest('此測試需要互動式 Windows 桌面')
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        process=subprocess.Popen([sys.executable,'-B','-X','utf8','-c',
                                  'from app import choose_file; choose_file()'],cwd=ROOT,
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        dialogs=[]
        def find_dialog(hwnd,_):
            owner=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
            title=ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd,title,128)
            if owner.value==process.pid and title.value=='開啟 CHM 電子書' and user32.IsWindowVisible(hwnd):
                dialogs.append(hwnd)
            return True
        try:
            deadline=time.monotonic()+10
            while not dialogs and time.monotonic()<deadline:
                user32.EnumWindows(callback(find_dialog),0)
                time.sleep(0.05)
            self.assertTrue(dialogs,'本次測試行程應顯示原生選檔對話框')
            time.sleep(0.5)
            self.assertEqual(user32.GetForegroundWindow(),dialogs[0],
                             '檔案對話框應在前景，不能被瀏覽器遮住')
        finally:
            if dialogs:
                user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
                user32.PostMessageW(dialogs[0],0x0111,2,0)  # IDCANCEL；只關閉本次 PID 的對話框。
            try:
                output=process.communicate(timeout=5)[0]
            except subprocess.TimeoutExpired:
                process.kill()
                output=process.communicate(timeout=5)[0]
        self.assertEqual(process.returncode,0,output.decode('utf-8',errors='replace'))

    def test_cmd_crlf_and_four_fixtures_plus_lzx(self):
        generate()
        acp=ctypes.windll.kernel32.GetACP()
        self.assertEqual(acp,950,'驗收環境應為 ACP 950；未修改系統設定')
        content=(ROOT/'開啟.cmd').read_bytes()
        self.assertNotIn(b'\n',content.replace(b'\r\n',b''))
        with tempfile.TemporaryDirectory() as temporary:
            for fixture in sorted(FIXTURES.glob('*.chm')):
                with self.subTest(fixture=fixture.name):
                    ready=Path(temporary)/'ready.json'
                    ready.unlink(missing_ok=True)
                    process=launch(fixture,ready)
                    info=None
                    try:
                        info=await_ready(process,ready)
                        def get(route):
                            with urlopen(info['url']+route,timeout=10) as response:
                                return response.read().decode('utf-8')
                        metadata=json.loads(get('api/book'))
                        results=json.loads(get('api/search?q='+quote('電腦')))
                        page=get('book/'+quote('章節/中文 頁面.htm'))
                        self.assertEqual(metadata['toc'][1]['path'],'/章節/中文 頁面.htm')
                        expected='電腦' if 'Big5' in fixture.name else '电脑'
                        self.assertIn(expected,page)
                        self.assertIn(expected,results[0]['snippet'])
                        self.assertNotIn('\ufffd',str(metadata)+str(results)+page)
                        if 'GB18030' in fixture.name:
                            self.assertIn('𠀀',page)
                    finally:
                        output=stop(process,info)
                    self.assertEqual(process.returncode,0,output.decode('utf-8',errors='replace'))

    def test_cmd_without_argument_opens_empty_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready=Path(temporary)/'ready.json'
            process=subprocess.Popen(cmd_line('--no-browser','--ready-file',ready),cwd=ROOT.parent,
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            info=None
            try:
                info=await_ready(process,ready)
                with urlopen(info['url']+'api/book',timeout=10) as response:
                    metadata=json.loads(response.read().decode('utf-8'))
                self.assertEqual(metadata['pages'],0)
                self.assertEqual(metadata['title'],'尚未開啟電子書')
            finally:
                output=stop(process,info)
            self.assertEqual(process.returncode,0,output.decode('utf-8',errors='replace'))

    def test_cmd_failure_chinese_message_and_nonzero_exit(self):
        result=subprocess.run(cmd_line(ROOT/'tests'/'不存在 空白.chm','--no-browser'),
                              input=b'\n',capture_output=True,cwd=ROOT.parent,timeout=10,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=(result.stdout+result.stderr).decode('utf-8',errors='strict')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('啟動失敗',output)
        self.assertNotIn('not recognized',output)
        self.assertIn('請按任意鍵',output)


if __name__ == '__main__':
    unittest.main()
