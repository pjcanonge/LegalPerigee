; ─────────────────────────────────────────────────────────────────────────────
; LegalPerigee — Inno Setup Installer Script
;
; Builds a professional Windows installer (.exe).
; Requires Inno Setup 6.x: https://jrsoftware.org/isdl.php
;
; To compile:
;   iscc installer.iss
;   OR open in Inno Setup IDE and click Build → Compile
;
; Output: installers\windows\Output\LegalPerigee-Setup.exe
; ─────────────────────────────────────────────────────────────────────────────

#define AppName      "LegalPerigee"
#define AppVersion   "1.2"
#define AppPublisher "LegalPerigee"
#define AppURL       "https://github.com/legalperigee"
#define AppExeName   "LegalPerigee.bat"
#define ProjectRoot  "..\.."

[Setup]
AppId={{8A3D2F1E-5B9C-4D7E-A1F6-C3B8E9D0F2A4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={userpf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
LicenseFile={#ProjectRoot}\installers\windows\LICENSE.txt
OutputDir=Output
OutputBaseFilename=LegalPerigee-Setup
SetupIconFile={#ProjectRoot}\installers\windows\LegalPerigee.ico
InfoAfterFile={#ProjectRoot}\installers\windows\quickstart.rtf
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardResizable=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\installers\windows\LegalPerigee.ico
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checked
Name: "quicklaunchicon"; Description: "Create a &Quick Launch shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Project files (exclude venv, git, temp files)
Source: "{#ProjectRoot}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: ".venv\*,.git\*,data\*.db,__pycache__\*,*.pyc,*.pyo,.DS_Store"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\installers\windows\{#AppExeName}"; \
    IconFilename: "{app}\installers\windows\LegalPerigee.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\installers\windows\{#AppExeName}"; \
    IconFilename: "{app}\installers\windows\LegalPerigee.ico"; \
    Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; \
    Filename: "{app}\installers\windows\{#AppExeName}"; \
    IconFilename: "{app}\installers\windows\LegalPerigee.ico"; \
    Tasks: quicklaunchicon

[Run]
; Run setup script after installation
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -File ""{app}\installers\windows\setup.ps1"""; \
    Description: "Install Python dependencies"; \
    StatusMsg: "Installing dependencies (this may take a few minutes)..."; \
    Flags: waituntilterminated

; Optionally launch after install
Filename: "{app}\installers\windows\{#AppExeName}"; \
    Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop any running instance
Filename: "taskkill.exe"; Parameters: "/f /im python.exe"; Flags: runhidden; RunOnceId: "KillPython"

[Code]
// Check for Python before installing
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  PythonFound: Boolean;
begin
  PythonFound := False;

  // Try to find Python 3.9+
  if Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    PythonFound := (ResultCode = 0);

  if not PythonFound then
    if Exec('python3', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      PythonFound := (ResultCode = 0);

  if not PythonFound then begin
    if MsgBox('Python 3.9 or later is required but was not found.' + #13#10 + #13#10 +
              'LegalPerigee will attempt to install Python automatically during setup.' + #13#10 +
              'Alternatively, install Python 3.11 from https://python.org' + #13#10 + #13#10 +
              'Continue with installation?',
              mbConfirmation, MB_YESNO) = IDNO then begin
      Result := False;
      Exit;
    end;
  end;

  Result := True;
end;
