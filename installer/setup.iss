#define MyAppName "EML Viewer"
#define MyAppPublisher "KwangBeomPark"
#define MyAppExeName "EmlViewer.exe"
#ifndef MyAppSourceDir
#define MyAppSourceDir "..\dist\EmlViewer"
#endif
#ifndef MyAppOutputDir
#define MyAppOutputDir "..\build\installer-preview"
#endif
#ifndef MyAppIcon
#define MyAppIcon "..\assets\app.ico"
#endif
#ifndef MyAppVersion
#define MyAppVersion "0.1.17"
#endif

[Setup]
AppId={{A9D9B7C3-04B8-4D2F-B28C-5B18C01C9CE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppMutex=EmlViewerMutex
CloseApplications=yes
CloseApplicationsFilter=EmlViewer.exe,App07_EmlViewer.exe
RestartApplications=no
DefaultDirName={localappdata}\Programs\EML Viewer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=no
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyAppOutputDir}
OutputBaseFilename=App07_EmlViewer_Setup_v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#MyAppIcon}
WizardStyle=modern
ChangesAssociations=yes
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.AssociateEmlTask=.eml/.msg 파일을 EML Viewer로 열기
english.AssociateEmlTask=Open .eml/.msg files with EML Viewer
korean.FileAssociationGroup=파일 연결:
english.FileAssociationGroup=File association:
korean.EmlFileTypeName=EML 이메일 파일
english.EmlFileTypeName=EML Email File
korean.MsgFileTypeName=Outlook MSG 이메일 파일
english.MsgFileTypeName=Outlook MSG Email File

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "associateeml"; Description: "{cm:AssociateEmlTask}"; GroupDescription: "{cm:FileAssociationGroup}"; Flags: checkedonce

[Dirs]
; Generated user settings are preserved on uninstall
Name: "{app}\UserSetting"; Flags: uninsneveruninstall

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Excludes: "UserSetting\*,UserSetting"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; AppUserModelID: "emlviewer.desktop.v1"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "emlviewer.desktop.v1"

[Registry]
Root: HKCU; Subkey: "Software\Classes\.eml"; ValueType: string; ValueName: ""; ValueData: "EMLViewer.eml"; Flags: uninsdeletevalue; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.eml"; ValueType: string; ValueName: ""; ValueData: "{cm:EmlFileTypeName}"; Flags: uninsdeletekey; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.eml\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.eml\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\.msg"; ValueType: string; ValueName: ""; ValueData: "EMLViewer.msg"; Flags: uninsdeletevalue; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.msg"; ValueType: string; ValueName: ""; ValueData: "{cm:MsgFileTypeName}"; Flags: uninsdeletekey; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.msg\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\EMLViewer.msg\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associateeml
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associateeml

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  PreviousAssociation: string;
begin
  if (CurStep = ssInstall) and WizardIsTaskSelected('associateeml') then
  begin
    if RegQueryStringValue(HKCU, 'Software\Classes\.eml', '', PreviousAssociation) then
    begin
      RegWriteStringValue(HKCU, 'Software\EMLViewer', 'PreviousEmlAssociation', PreviousAssociation);
    end;
    if RegQueryStringValue(HKCU, 'Software\Classes\.msg', '', PreviousAssociation) then
    begin
      RegWriteStringValue(HKCU, 'Software\EMLViewer', 'PreviousMsgAssociation', PreviousAssociation);
    end;
  end;
end;

procedure CleanStartupShortcutIfTargetMatches;
var
  StartupLnk: string;
  WshShell: Variant;
  Shortcut: Variant;
  TargetExe: string;
begin
  StartupLnk := ExpandConstant('{userstartup}\{#MyAppName}.lnk');
  if FileExists(StartupLnk) then
  begin
    try
      WshShell := CreateOleObject('WScript.Shell');
      Shortcut := WshShell.CreateShortcut(StartupLnk);
      TargetExe := Shortcut.TargetPath;
      if CompareText(TargetExe, ExpandConstant('{app}\{#MyAppExeName}')) = 0 then
      begin
        DeleteFile(StartupLnk);
      end;
    except
      // Ignore if WScript.Shell is unavailable
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  PreviousAssociation: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    CleanStartupShortcutIfTargetMatches;
    if RegQueryStringValue(HKCU, 'Software\EMLViewer', 'PreviousEmlAssociation', PreviousAssociation) then
    begin
      RegWriteStringValue(HKCU, 'Software\Classes\.eml', '', PreviousAssociation);
    end;
    if RegQueryStringValue(HKCU, 'Software\EMLViewer', 'PreviousMsgAssociation', PreviousAssociation) then
    begin
      RegWriteStringValue(HKCU, 'Software\Classes\.msg', '', PreviousAssociation);
    end;
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\EMLViewer');
  end;
end;
