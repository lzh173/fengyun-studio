@echo off
rem ?? FY-Sat Studio ????
rem ??????: fysat-gui "Y:\download-data\xxx.HDF"
setlocal
set PY="E:\venv\fysat\Scripts\pythonw.exe"
set PYTHONPATH=E:\CODEX-NOworkspaces\fysat\src;%PYTHONPATH%
if "%~1"=="" (
  start "" %PY% -m fysat.gui.app
) else (
  start "" %PY% -m fysat.gui.app "%~1"
)
