param([Parameter(Mandatory)][string]$Exe)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$Exe = (Resolve-Path -LiteralPath $Exe).Path
$temp = New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString()))

function Start-Reader($name, $book) {
    $ready = Join-Path $temp.FullName "$name.json"
    $arguments = "--ready-file `"$ready`""
    if ($book) { $arguments += " `"$book`"" }
    $process = Start-Process -PassThru -FilePath $Exe -ArgumentList $arguments
    $until = [DateTime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 150
        if ($process.HasExited) { throw "Reader exited during startup: $($process.ExitCode)" }
        if (Test-Path -LiteralPath $ready) {
            $info = Get-Content -Raw -Encoding UTF8 -LiteralPath $ready | ConvertFrom-Json
            $child = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($info.pid)" |
                Where-Object { $_.Name -eq 'ReaderWindow.exe' } | Select-Object -First 1
            if ($child) {
                $browser = Get-Process -Id $child.ProcessId
                if ($browser.MainWindowHandle -ne 0) {
                    return @{Process=$process; Browser=$browser; Url=$info.url; Pid=$info.pid}
                }
            }
        }
    } while ([DateTime]::UtcNow -lt $until)
    throw 'Reader window did not appear'
}

function Assert-Closed($reader) {
    if (!$reader.Process.WaitForExit(12000) -or $reader.Process.ExitCode -ne 0) { throw 'EXE did not exit cleanly' }
    if (!$reader.Browser.WaitForExit(2000)) { throw 'Window process still alive' }
    if (Get-Process -Id $reader.Pid -ErrorAction SilentlyContinue) { throw 'Server process still alive' }
    $client = New-Object Net.Sockets.TcpClient
    try {
        try { $client.Connect('127.0.0.1', ([uri]$reader.Url).Port) } catch [Net.Sockets.SocketException] { return }
        throw 'Reader port still listening'
    } finally { $client.Dispose() }
}

function Find-ReaderWindow($reader) {
    $root = [Windows.Automation.AutomationElement]::RootElement
    $owner = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::ProcessIdProperty, $reader.Browser.Id)
    $root.FindAll([Windows.Automation.TreeScope]::Children, $owner) |
        Where-Object { $_.Current.Name -like '*CHM 閱讀器*' } | Select-Object -First 1
}

$readers = @()
try {
    $book = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'fixtures/測試 Big5.chm')).Path
    $first = Start-Reader 'button' $book
    $readers += $first
    $second = Start-Reader 'system-close'
    $readers += $second
    $condition = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::NameProperty, '關閉閱讀器')
    $until = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $root = Find-ReaderWindow $first
        if ($root -and $root.Current.Name -like '*測試書籍 Big5*') {
            $button = $root.FindFirst([Windows.Automation.TreeScope]::Descendants, $condition)
        }
        if ($button) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $until)
    if (!$button) { throw 'Close Reader button missing in the dedicated reader window' }
    $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
    Assert-Closed $first
    $null = Invoke-RestMethod ($second.Url+'api/book') -TimeoutSec 3
    $secondWindow = Find-ReaderWindow $second
    $secondWindow.GetCurrentPattern([Windows.Automation.WindowPattern]::Pattern).Close()
    Assert-Closed $second
    'PASS: Close Reader and window X both closed the window, EXE and port. Second reader remained independent.'
} finally {
    foreach ($reader in $readers) {
        if (!$reader.Process.HasExited) {
            try { $null = Invoke-RestMethod ($reader.Url+'api/exit') -Method Post -Body '{}' -TimeoutSec 3 } catch {}
        }
    }
    Get-ChildItem -LiteralPath $temp.FullName -Filter '*.json' | Remove-Item
    $temp.Delete()
}
