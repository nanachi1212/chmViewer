"""管理本次閱讀器的 Windows 視窗與專用 WebView2 設定檔。"""
from pathlib import Path
import subprocess
import sys
import tempfile


def host_path():
    root = Path(__file__).resolve().parents[1]
    if not getattr(sys, 'frozen', False):
        root = root / 'build'
    return root / 'window' / 'ReaderWindow.exe'


class ReaderWindow:
    def __init__(self, host, url):
        self.profile = tempfile.TemporaryDirectory(prefix='chm-window-', ignore_cleanup_errors=True)
        try:
            self.process = subprocess.Popen([host, url, self.profile.name], stdin=subprocess.PIPE)
        except OSError:
            self.profile.cleanup()
            raise

    def closed(self):
        return self.process.poll() is not None

    def close(self):
        try:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait()
        finally:
            self.profile.cleanup()
