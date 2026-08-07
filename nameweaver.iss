#define AppName    "Nameweaver"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppExe     "Nameweaver.exe"
#define AppDir     "dist\Nameweaver"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Muhammed Enes Alpler
AppPublisherURL=https://github.com/thealps01-netizen/nameweaver
AppSupportURL=https://github.com/thealps01-netizen/nameweaver/issues
AppUpdatesURL=https://github.com/thealps01-netizen/nameweaver/releases
; AppId uniquely identifies this app to Windows — never change this GUID after release
AppId={{393AD771-10ED-4B32-801C-E5CCFEC8BA3D}
; CloseApplications uses Restart Manager to gracefully close the running app before install
CloseApplications=yes
RestartApplications=no
; Installer exe version info (shown in file properties)
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoCompany=Muhammed Enes Alpler
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=Nameweaver_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\nameweaver.ico
SetupIconFile=nameweaver.ico
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "nameweaver.ico";         DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExe}"; IconFilename: "{app}\nameweaver.ico"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}";        Filename: "{app}\{#AppExe}"; IconFilename: "{app}\nameweaver.ico"; Tasks: desktopicon

[Run]
; Interactive install — user can choose to launch from the wizard
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; Silent install (auto-update) — restart app automatically after install completes
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent

[UninstallRun]
; Force-kill the app before uninstaller tries to delete the exe
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden waituntilterminated; RunOnceId: "KillNameweaver"

[UninstallDelete]
; Clean up app directory if empty after uninstall
; (settings.json is intentionally kept — user config is preserved on upgrade)
Type: dirifempty; Name: "{app}"

[Code]
{ Shell notification — forces Windows to flush the icon cache }
procedure SHChangeNotify(wEventId: Integer; uFlags: Cardinal; dwItem1: Integer; dwItem2: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

{ After all files are written, tell the shell to refresh its icon cache. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    SHChangeNotify($08000000, $1000, 0, 0);  { SHCNE_ASSOCCHANGED | SHCNF_FLUSH }
end;
