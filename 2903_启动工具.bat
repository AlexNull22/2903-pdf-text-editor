@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\2903_运行环境\Scripts\python.exe" (
  "%USERPROFILE%\2903_运行环境\Scripts\python.exe" -B "2903_桌面工具.py"
) else (
  py -3 -B "2903_桌面工具.py"
)
if errorlevel 1 (
  echo 启动失败。请先按2903_使用说明安装依赖。
  pause
)
endlocal
