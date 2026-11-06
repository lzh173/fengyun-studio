@echo off
rem ============================================================
rem  FY-Sat Studio - GUI entry (no console window)
rem
rem  Usage:
rem    bin\fysat-gui.cmd                        (empty workspace)
rem    bin\fysat-gui.cmd "D:\samples\xxx.HDF"  (open a product directly)
rem    bin\fysat-gui.cmd "D:\samples"           (open a directory)
rem
rem  Python resolution order:
rem    1) %%FYSAT_PYTHON%%   (point it at a specific interpreter if you like)
rem    2) pythonw on PATH, then python on PATH
rem ============================================================
setlocal

set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"

set "PYEXE=%FYSAT_PYTHON%"
if "%PYEXE%"=="" (
  where pythonw >nul 2>nul && (set "PYEXE=pythonw") || (set "PYEXE=python")
)

if "%~1"=="" (
  start "" "%PYEXE%" -m fysat.gui.app
) else (
  start "" "%PYEXE%" -m fysat.gui.app "%~1"
)
