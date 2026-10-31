@echo off
rem Builds GemRB (Release) and installs it over D:\Games\GemRB, replacing the binaries and scripts.
rem Usage: build_install.bat          - build and install
rem        build_install.bat run      - build, install and start the game

setlocal
set BUILD_DIR=%~dp0build
set GAME_DIR=D:\Games\GemRB

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

echo.
echo === Done: %GAME_DIR% is up to date ===

if /i "%~1"=="run" (
	pushd "%GAME_DIR%"
	gemrb.exe
	popd
)
endlocal
