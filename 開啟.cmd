@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto failed
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -X utf8 "%~dp0app.py" %*
if errorlevel 1 goto failed
popd
exit /b 0
:python
where python >nul 2>nul
if errorlevel 1 goto missing
python -X utf8 "%~dp0app.py" %*
if errorlevel 1 goto failed
popd
exit /b 0
:missing
echo 找不到 Python。請先安裝含 tkinter 的 Python 3.11 或更新版本。
goto failed
:failed
echo 啟動失敗。請確認 CHM 路徑、Python 與 7-Zip 是否可用，詳細原因請見上方訊息。請按任意鍵結束。

pause >nul

exit /b 1
