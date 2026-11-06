@echo off
rem ============================================================
rem  FY-Sat Studio - command line entry
rem
rem  Usage:
rem    bin\fysat.cmd info  "D:\samples\FY3D_MERSI_GBAL_L1_...HDF"
rem    bin\fysat.cmd batch "D:\samples" --out out\batch
rem
rem  Python resolution order:
rem    1) %%FYSAT_PYTHON%%   (point it at a specific interpreter if you like)
rem    2) python on PATH
rem ============================================================
setlocal

set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"

set "PYEXE=%FYSAT_PYTHON%"
if "%PYEXE%"=="" set "PYEXE=python"

"%PYEXE%" -m fysat.cli %*
exit /b %ERRORLEVEL%
