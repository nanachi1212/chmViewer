"""以 Windows 內建的 .NET Framework 編譯器建立 x64 WebView2 視窗。"""
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'microsoft.web.webview2'
VERSION = '1.0.4314.35'
DIGEST = '90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4'


def build():
    output = ROOT / 'build' / 'window'
    output.mkdir(parents=True, exist_ok=True)
    package = output.parent / f'{PACKAGE}.{VERSION}.nupkg'
    if not package.exists() or hashlib.sha256(package.read_bytes()).hexdigest() != DIGEST:
        with urlopen(f'https://api.nuget.org/v3-flatcontainer/{PACKAGE}/{VERSION}/{package.name}', timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != DIGEST:
            raise ValueError('WebView2 SDK 的 SHA-256 與指定版本不符。')
        package.write_bytes(data)
    assemblies = ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']
    with zipfile.ZipFile(package) as archive:
        for entry in [*('lib/net462/' + name for name in assemblies), 'runtimes/win-x64/native/WebView2Loader.dll', 'LICENSE.txt']:
            (output / Path(entry).name).write_bytes(archive.read(entry))
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([compiler, '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001', '/optimize+',
                    '/win32icon:' + str(ROOT / 'assets' / 'chmviewer.ico'),
                    '/out:ReaderWindow.exe', *('/reference:' + name for name in assemblies),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    ROOT / 'windows' / 'ReaderWindow.cs'], cwd=output, check=True)


if __name__ == '__main__':
    build()
