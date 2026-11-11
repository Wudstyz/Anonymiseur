; Installateur d'Anonymiseur pour Windows (Inno Setup 6).
; Construit par windows\build_windows.ps1 : iscc /DAppVersion=1.1 /DSourceDir=<dossier dist\Anonymiseur> windows\installer.iss
#ifndef AppVersion
  #define AppVersion "1.1"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Anonymiseur"
#endif

[Setup]
AppId={{B7E3A1C2-5D4F-4E8A-9C3B-2F6A1D8E7B40}
AppName=Anonymiseur
AppVersion={#AppVersion}
AppPublisher=Wudstyz
AppPublisherURL=https://github.com/Wudstyz/Anonymiseur
AppSupportURL=https://github.com/Wudstyz/Anonymiseur/issues
DefaultDirName={autopf}\Anonymiseur
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Anonymiseur-{#AppVersion}-x64-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\App.ico
UninstallDisplayIcon={app}\App.ico
LicenseFile=..\LICENSE

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; Flags: unchecked
Name: "sendto"; Description: "Ajouter « Anonymiseur » au menu « Envoyer vers » (clic droit sur un fichier)"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Anonymiseur"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\App.ico"
Name: "{autodesktop}\Anonymiseur"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\App.ico"; Tasks: desktopicon
Name: "{sendto}\Anonymiseur"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\App.ico"; Tasks: sendto

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; Description: "Lancer Anonymiseur"; Flags: nowait postinstall skipifsilent
