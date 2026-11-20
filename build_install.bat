@echo off
rem Builds GemRB (Release) and installs it over C:\Games\GemRB, replacing the binaries and scripts.
rem Usage: build_install.bat          - build and install
rem        build_install.bat run      - build, install and start the game

setlocal
set BUILD_DIR=%~dp0build
set GAME_DIR=C:\Games\GemRB

rem Never delete or copy C:\Games\GemRB\upscaled (hi-res art, UPSCALE_PLAN.md).
rem the install step overwrites GemRB.cfg with the default sample, so keep the real one safe
set CFG_BACKUP=%TEMP%\GemRB.cfg.keep
if exist "%GAME_DIR%\GemRB.cfg" copy /y "%GAME_DIR%\GemRB.cfg" "%CFG_BACKUP%" >nul

echo === Building and installing to %GAME_DIR% ===
rem /m:1 keeps the compiler from running out of heap space
cmake --build "%BUILD_DIR%" --config Release --target INSTALL -- /m:1 /v:minimal /nologo
set BUILD_RESULT=%errorlevel%

if exist "%CFG_BACKUP%" (
	copy /y "%CFG_BACKUP%" "%GAME_DIR%\GemRB.cfg" >nul
	del "%CFG_BACKUP%"
)

if not "%BUILD_RESULT%"=="0" (
	echo.
	echo *** Build failed, check the errors above ***
	pause
	exit /b 1
)

rem switch every feature on in the installed config (tools\dev_settings.ini)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\apply_dev_settings.ps1" -GameDir "%GAME_DIR%"
if errorlevel 1 echo *** Could not apply tools\dev_settings.ini ***

rem CMake INSTALL(DIRECTORY) has been skipping newly added override files; copy sounds ourselves
if not exist "%GAME_DIR%\override\pst" mkdir "%GAME_DIR%\override\pst"
copy /y "%~dp0gemrb\override\pst\*.ogg" "%GAME_DIR%\override\pst\" >nul 2>nul
copy /y "%~dp0gemrb\override\pst\*.wav" "%GAME_DIR%\override\pst\" >nul 2>nul

echo.
echo === Done: %GAME_DIR% is up to date ===

if /i "%~1"=="run" (
	pushd "%GAME_DIR%"
	gemrb.exe
	popd
)
endlocal
