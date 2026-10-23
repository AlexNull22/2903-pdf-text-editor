@echo off
chcp 65001 >nul
setlocal
set "TASK2903_URL=https://www.upwork.com/jobs/span-class-highlight-Python-span-PDF-Text-Editor_~022110545273714922695/?referrer_url_path=/nx/search/jobs"
if exist "%ProgramFiles%\Mozilla Firefox\firefox.exe" (
    start "" "%ProgramFiles%\Mozilla Firefox\firefox.exe" "%TASK2903_URL%"
    exit /b 0
)
if exist "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" (
    start "" "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" "%TASK2903_URL%"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Mozilla Firefox\firefox.exe" (
    start "" "%LOCALAPPDATA%\Mozilla Firefox\firefox.exe" "%TASK2903_URL%"
    exit /b 0
)
where firefox.exe >nul 2>nul
if errorlevel 1 (
    echo 未找到 Firefox。请安装 Firefox 后重新运行本文件。
    pause
    exit /b 1
)
start "" firefox.exe "%TASK2903_URL%"
endlocal
