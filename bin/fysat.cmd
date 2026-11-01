@echo off
rem FY-Sat Studio ?????
rem ??: fysat info <??>    fysat export <??> <??> --kind tiff --out a.tif
setlocal
set PY="E:\venv\fysat\Scripts\python.exe"
set PYTHONPATH=E:\CODEX-NOworkspaces\fysat\src;%PYTHONPATH%
%PY% -m fysat.cli %*
