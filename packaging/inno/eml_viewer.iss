#define MyAppName "EML Viewer"
#define MyAppPublisher "KwangBeomPark"
#define MyAppExeName "EmlViewer.exe"
#define MyAppIcon "..\..\assets\app.ico"
#ifndef MyAppVersion
#define MyAppVersion "0.1.15"
#endif

[Setup]
AppId={{A9D9B7C3-04B8-4D2F-B28C-5B18C01C9CE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppMutex=EmlViewerMutex
CloseApplications=yes
DefaultDirName={localappdata}\Programs\EML Viewer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=no
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\installer
OutputBaseFilename=App07_EmlViewer_Setup_v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#MyAppIcon}
WizardStyle=modern
ChangesAssociations=yes

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

[Files]
Source: "..\..\dist\EmlViewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  PreviousAssociation: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
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
