; Safeer Browser for Windows - Inno Setup 6 script
; Built by windows/build_windows.py package:
;   ISCC /DAppVersion=1.0.0 /DAppSourceDir=...\dist\SafeerBrowser /DAppOutputDir=... /DAppIconFile=...\safeer.ico installer.iss
; Safeer Player (naloga 103): isti skript z /DPredvajalnik da SafeerPlayer-<razlicica>-windows-x64-setup.exe iz ISTEGA
; zgrajenega paketa (isti _internal, SafeerOS.exe --predvajalnik). En skript namesto dveh, da se ne razideta.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppSourceDir
  #define AppSourceDir "..\build\windows\dist\SafeerBrowser"
#endif
#ifndef AppOutputDir
  #define AppOutputDir "..\build\windows\out"
#endif
#ifndef AppIconFile
  #define AppIconFile "..\build\windows\safeer.ico"
#endif
#ifdef Predvajalnik
; Svoj AppId, svoja mapa in svoj vnos v Programi in funkcije: Player se namesti in odstrani neodvisno od Browserja.
  #define AppName "Safeer Player"
  #define AppExe "SafeerOS.exe"
  #define AppArgs "--predvajalnik"
  #define AppAumid "Safeer.Player"
  #define AppBase "SafeerPlayer"
  #define AppUrl "https://safeer.si/"
#else
  #define AppName "Safeer Browser"
  #define AppExe "SafeerBrowser.exe"
  #define AppArgs ""
  #define AppAumid "Safeer.Browser"
  #define AppBase "SafeerBrowser"
  #define AppUrl "https://safeer.si/browser/"
#endif
#define ClientKey "Software\Clients\StartMenuInternet\SafeerBrowser"

[Setup]
#ifdef Predvajalnik
AppId={{01C74370-7B72-41D5-9695-C6CA57BAE246}
#else
AppId={{6D1F3A52-8C4B-4E27-9B61-5A0E7C3D9F14}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Safeer
AppPublisherURL=https://safeer.si
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#AppOutputDir}
OutputBaseFilename={#AppBase}-{#AppVersion}-windows-x64-setup
SetupIconFile={#AppIconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
#ifdef Predvajalnik
; Player ne registrira brskalnika ne povezav (http, .html): to ostane Safeer Browser.
ChangesAssociations=no
#else
ChangesAssociations=yes
#endif
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

[Languages]
Name: "slovenian"; MessagesFile: "compiler:Languages\Slovenian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
#ifdef Predvajalnik
; Samo Safeer Player: brez bliznjic Browser in Safeer OS, ceprav sta programa v istem paketu (isti _internal).
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "{#AppArgs}"; AppUserModelID: "{#AppAumid}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "{#AppArgs}"; Tasks: desktopicon; AppUserModelID: "{#AppAumid}"
#else
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Safeer.Browser"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; AppUserModelID: "Safeer.Browser"
Name: "{autoprograms}\Safeer OS"; Filename: "{app}\SafeerOS.exe"; AppUserModelID: "Safeer.OS"
Name: "{autodesktop}\Safeer OS"; Filename: "{app}\SafeerOS.exe"; Tasks: desktopicon; AppUserModelID: "Safeer.OS"
#endif

#ifndef Predvajalnik
[Registry]
; Browser registration so Windows lists Safeer Browser in Settings > Apps > Default apps.
Root: HKA; Subkey: "{#ClientKey}"; ValueType: string; ValueName: ""; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "{#ClientKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "{#ClientKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"""
Root: HKA; Subkey: "{#ClientKey}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKA; Subkey: "{#ClientKey}\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "{#ClientKey}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Fast browser with protection against ads and web threats."
Root: HKA; Subkey: "{#ClientKey}\Capabilities\StartMenu"; ValueType: string; ValueName: "StartMenuInternet"; ValueData: "SafeerBrowser"
Root: HKA; Subkey: "{#ClientKey}\Capabilities\URLAssociations"; ValueType: string; ValueName: "http"; ValueData: "SafeerBrowserURL"
Root: HKA; Subkey: "{#ClientKey}\Capabilities\URLAssociations"; ValueType: string; ValueName: "https"; ValueData: "SafeerBrowserURL"
Root: HKA; Subkey: "{#ClientKey}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".htm"; ValueData: "SafeerBrowserHTML"
Root: HKA; Subkey: "{#ClientKey}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".html"; ValueData: "SafeerBrowserHTML"
Root: HKA; Subkey: "{#ClientKey}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xhtml"; ValueData: "SafeerBrowserHTML"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "{#ClientKey}\Capabilities"; Flags: uninsdeletevalue

Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL"; ValueType: string; ValueName: ""; ValueData: "Safeer Browser URL"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Safeer Browser URL"
Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SafeerBrowserURL\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

Root: HKA; Subkey: "Software\Classes\SafeerBrowserHTML"; ValueType: string; ValueName: ""; ValueData: "Safeer Browser HTML Document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SafeerBrowserHTML\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKA; Subkey: "Software\Classes\SafeerBrowserHTML\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SafeerBrowserHTML\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

Root: HKA; Subkey: "Software\Classes\.htm\OpenWithProgids"; ValueType: string; ValueName: "SafeerBrowserHTML"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.html\OpenWithProgids"; ValueType: string; ValueName: "SafeerBrowserHTML"; ValueData: ""; Flags: uninsdeletevalue
#endif

[Run]
#ifdef Predvajalnik
Filename: "{app}\{#AppExe}"; Parameters: "{#AppArgs}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#else
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#endif
