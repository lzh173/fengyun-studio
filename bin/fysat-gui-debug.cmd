@echo off
rem ????? GUI ????????????
setlocal
set PY="E:\venv\fysat\Scripts\python.exe"
set PYTHONPATH=E:\CODEX-NOworkspaces\fysat\src;%PYTHONPATH%
%PY% -m fysat.gui.app %*
pause
