[Setup]
AppId={{F638DC5F-601E-448A-93F4-6824633E270A}
AppName=邮箱连点器 QuickSender
AppVersion=2.1.0
DefaultDirName={localappdata}\Programs\QuickSender
DefaultGroupName=邮箱连点器 QuickSender
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=QuickSender-2.1.0-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=QuickSender.ico
UninstallDisplayIcon={app}\QuickSender.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "dist\QuickSender\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\邮箱连点器 QuickSender"; Filename: "{app}\QuickSender.exe"
Name: "{autodesktop}\邮箱连点器 QuickSender"; Filename: "{app}\QuickSender.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\QuickSender.exe"; Description: "Launch QuickSender"; Flags: nowait postinstall skipifsilent
