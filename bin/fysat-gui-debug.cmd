@echo off
rem ============================================================
rem  FY-Sat Studio - GUI entry WITH console (for troubleshooting)
rem
rem  Keeps the console open so Python tracebacks stay visible.
rem  Same Python resolution as fysat-gui.cmd:
rem    1) %%FYSAT_PYTHON%%   2) python on PATH
rem ============================================================
setlocal

set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"

set "PYEXE=%FYSAT_PYTHON%"
if "%PYEXE%"=="" set "PYEXE=python"

"%PYEXE%" -m fysat.gui.app %*
echo.
echo ---- exited with code %ERRORLEVEL% ----
pause
