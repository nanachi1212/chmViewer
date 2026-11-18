# CHM 閱讀器

- **用途**：在繁體中文 Windows 閱讀 GB2312、GBK、GB18030、UTF-8、Big5 編碼的 CHM，並支援繁簡互通的全文搜尋。
- **安裝版（Windows x64）**：[下載 CHMViewer-Setup-x64.exe](https://github.com/nanachi1212/chmViewer/releases/latest/download/CHMViewer-Setup-x64.exe)。安裝精靈會將程式加入目前使用者的開始功能表及 Windows「開啟方式」。保留最後一頁的「開啟 Windows 設定」勾選，在設定中點選 .chm，選「CHM 閱讀器」並設為預設，以後雙擊 CHM 即可閱讀。
- **Windows x64 可攜版**：[下載最新版 CHMViewer.exe](https://github.com/nanachi1212/chmViewer/releases/latest/download/CHMViewer.exe)。雙擊後按「開啟 CHM」選書，也可以直接把 CHM 檔拖到 EXE 上。Python 和 7-Zip 解壓元件已內附。
- **目錄與結束搜尋**：目錄預設收合。點章節箭頭展開或收合，點頁名閱讀。「返回完整目錄」或清空搜尋框會保留目前閱讀頁及目錄展開狀態。
- **內文字級**：工具列可選 75% 至 200%，選「100%（原始）」還原原書排版。換頁、開另一本書及下次啟動時會沿用字級。
- **設定保存位置**：安裝版與可攜版共用目前 Windows 使用者的 `%LOCALAPPDATA%\CHMViewer\font-size.txt`。更新或解除安裝程式會保留此設定。
- **關閉視窗**：可攜版使用 Windows 11 內建的 Microsoft Edge WebView2 Runtime 顯示獨立閱讀視窗。按「關閉閱讀器」或視窗右上角 × 都會結束該視窗與背景閱讀程式。
- **編碼與搜尋**：預設自動偵測。舊書標記有誤時，可從「編碼」切換 Big5、UTF-8 或 GB18030（含 GBK、GB2312）。輸入關鍵字後按 Enter，點選結果會開啟原頁、標示命中並捲至第一處。結果超過 100 頁時可按「顯示更多結果」。
- **從原始碼執行**：安裝含 tkinter 的 Python 與 7-Zip，執行 `python windows/build_window.py` 建立獨立視窗，再雙擊 `開啟.cmd`。略過視窗建置時，開發版會改用預設瀏覽器分頁。
- **重建 EXE**：使用 64 位元 Windows、Python 3.15、PyInstaller 6.22.3，以及安裝在 `%ProgramFiles%\7-Zip` 的 64 位元 7-Zip，執行 `python -m PyInstaller CHMViewer.spec`。首次建置會從 NuGet 下載指定版本的 WebView2 SDK、核對 SHA-256，並以 Windows 的 .NET Framework 編譯器建立視窗。
- **驗證**：`python -m unittest -v`。已安裝 Edge 與 Playwright 的環境可執行 `python -m tests.browser_smoke --exe dist\CHMViewer.exe`；加上 `--htw "完整路徑\无限恐怖规则HTW2.12.3.chm"` 可驗證大型書籍。
- **建置安裝版**：先建置可攜版，再執行 `ISCC.exe windows\CHMViewer.iss`（Inno Setup 7）。產物位於 `dist\CHMViewer-Setup-x64.exe`。
