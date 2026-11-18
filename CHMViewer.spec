from pathlib import Path
import os
import subprocess
import sys

seven_zip = Path(os.environ['ProgramFiles']) / '7-Zip'
subprocess.run([sys.executable, Path(SPECPATH) / 'windows/build_window.py'], check=True)
app = Analysis(
    ['app.py'],
    binaries=[(str(seven_zip / name), '7-Zip') for name in ('7z.exe', '7z.dll')],
    datas=[('reader/ui.html', 'reader'), ('vendor/*.txt', 'vendor'), ('build/window/*', 'window'),
           ('THIRD_PARTY.txt', '.'), (str(seven_zip / 'License.txt'), '7-Zip'),
           (str(Path(sys.base_prefix) / 'LICENSE.txt'), 'Python')],
)
exe = EXE(PYZ(app.pure), app.scripts, app.binaries, app.datas, [],
          name='CHMViewer', console=False, upx=False)
