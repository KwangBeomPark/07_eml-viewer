; Compatibility entry point. Edit installer/setup.iss only.
#define MyAppIcon "..\..\assets\app.ico"
#ifndef MyAppSourceDir
#define MyAppSourceDir "..\..\dist\EmlViewer"
#endif
#ifndef MyAppOutputDir
#define MyAppOutputDir "..\..\build\installer-preview"
#endif
#include "..\..\installer\setup.iss"
