[Setup]
AppId={{A44EB3E3-18D6-4C3F-9485-0091A2955CF1}
AppName=双功能自动连点TXT工具
AppVersion=3.0.0
DefaultDirName={localappdata}\Programs\AutoClickTXT
DefaultGroupName=双功能自动连点TXT工具
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=AutoClickTXT-3.0.0-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AutoClickTXT.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\AutoClickTXT\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\双功能自动连点TXT工具"; Filename: "{app}\AutoClickTXT.exe"
Name: "{autodesktop}\双功能自动连点TXT工具"; Filename: "{app}\AutoClickTXT.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoClickTXT.exe"; Description: "Launch application"; Flags: nowait postinstall skipifsilent
