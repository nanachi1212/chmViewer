#define AppName "CHM 閱讀器"
#define AppVersion "1.3.1"
#define ProgId "CHMViewer.Document"

[Setup]
AppId=nanachi1212.CHMViewer
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppPublisher=nanachi1212
AppPublisherURL=https://github.com/nanachi1212/chmViewer
DefaultDirName={localappdata}\Programs\CHMViewer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
ChangesAssociations=yes
SetupIconFile=..\assets\chmviewer.ico
UninstallDisplayIcon={app}\CHMViewer.exe
OutputDir=..\dist
OutputBaseFilename=CHMViewer-Setup-x64
WizardStyle=modern
Compression=lzma2

[Languages]
Name: "zhTW"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Files]
Source: "..\dist\CHMViewer.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\CHMViewer.exe"

[Registry]
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueData: "CHM 電子書"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueData: """{app}\CHMViewer.exe"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\CHMViewer.exe"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\CHMViewer.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.chm\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\CHMViewer.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\CHMViewer.exe\SupportedTypes"; ValueType: string; ValueName: ".chm"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CHMViewer.exe\shell\open\command"; ValueType: string; ValueData: """{app}\CHMViewer.exe"" ""%1"""
Root: HKCU; Subkey: "Software\CHMViewer\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\CHMViewer\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "閱讀 CHM 電子書，支援繁簡全文搜尋與內文字級調整。"
Root: HKCU; Subkey: "Software\CHMViewer\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\CHMViewer.exe"",0"
Root: HKCU; Subkey: "Software\CHMViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".chm"; ValueData: "{#ProgId}"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "CHMViewer"; ValueData: "Software\CHMViewer\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "ms-settings:defaultapps?registeredAppUser=CHMViewer"; Description: "開啟 Windows 設定，將 .chm 的預設應用程式選為「{#AppName}」"; Flags: shellexec postinstall nowait skipifsilent
