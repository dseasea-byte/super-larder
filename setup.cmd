@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo.
  echo [!] 没找到 Python。请先安装 Python 3.9 以上版本：
  echo     https://www.python.org/downloads/
  echo     安装时务必勾选 "Add Python to PATH"
  echo.
  pause
  exit /b 1
)

%PY% setup.py %*
pause
