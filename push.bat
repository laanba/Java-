@echo off
chcp 65001 >nul
echo 正在提交今日Java笔记...

REM 用 PowerShell 获取标准日期格式 (YYYY-MM-DD)
for /f %%i in ('powershell -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i

git add .
git commit -m "Daily-Update: %TODAY% 项目进度同步"

REM 这里统一改成推送到 main（因为刚才已经改好了）
git push origin main

pause