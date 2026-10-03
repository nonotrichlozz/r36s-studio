; Installeur Windows de R36S Studio (Inno Setup 6, docs/claude/packaging.md).
; Construit par .github/workflows/release.yml après PyInstaller :
;   iscc /DAppVersion=0.1.0 packaging\windows_installer.iss
; Sortie : dist\R36S-Studio-Setup.exe (nom sans numéro de version). Vendu sur
; la boutique, jamais publié sur GitHub (scripts/publish_release.sh).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; GUID fixe : une nouvelle version remplace l'ancienne au lieu de
; s'installer à côté. Ne jamais le changer.
AppId={{C8702075-D7C3-4580-82A8-05843D27B58E}
AppName=R36S Studio
AppVersion={#AppVersion}
AppPublisher=nonotrichlozz
AppPublisherURL=https://github.com/nonotrichlozz/r36s-studio
; Pas d'UAC à l'installation : l'app le demande elle-même pour écrire sur
; la carte SD (gui/elevate.py).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\R36S Studio
DefaultGroupName=R36S Studio
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=..\dist
OutputBaseFilename=R36S-Studio-Setup
SetupIconFile=r36s_studio.ico
UninstallDisplayIcon={app}\R36S Studio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\R36S Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"
Source: "..\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"

[InstallDelete]
; Ancien _internal d'une version précédente : évite de mélanger des DLL.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\R36S Studio"; Filename: "{app}\R36S Studio.exe"
Name: "{autodesktop}\R36S Studio"; Filename: "{app}\R36S Studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\R36S Studio.exe"; Description: "Lancer R36S Studio"; Flags: nowait postinstall skipifsilent
