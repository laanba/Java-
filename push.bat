@echo off
echo 正在提交今日Java笔记...
git add .
git commit -m "Daily-Update: %date:~0,4%年%date:~5,2%月%date:~8,2%日 项目进度同步"
git push origin main
pause