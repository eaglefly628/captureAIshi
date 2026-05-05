@echo off
:: deploy_demo.bat -- push current branch to gitee + redeploy on ECS
::
:: Workflow:
::   1. git push gitee claudeMainBranch       (Windows -> Gitee)
::   2. ssh ECS -> git pull from gitee + docker build + restart container
::
:: Prereqs:
::   - 'gitee' remote configured in this repo (git remote add gitee <url>)
::   - SSH access to root@139.224.204.231 (key-based ideally; password
::     prompt OK -- you'll be asked once per run)
::   - On the ECS, ~/captureaishi must already exist and have 'gitee' as
::     a remote (or 'origin' pointing at gitee, depending on initial clone)

setlocal

set BRANCH=claudeMainBranch
set ECS_HOST=root@139.224.204.231
set ECS_REPO_DIR=~/captureaishi
set CONTAINER=aishi-demo
set IMAGE=captureaishi-demo
set HOST_PORT=9000
set CONTAINER_PORT=8080

echo.
echo === [1/3] git push gitee %BRANCH% ===
git push gitee %BRANCH%
if errorlevel 1 (
    echo.
    echo Gitee push failed. Check 'git remote -v' has a 'gitee' entry.
    exit /b 1
)

echo.
echo === [2/3] ssh %ECS_HOST% -- pull + rebuild + restart ===
ssh %ECS_HOST% "cd %ECS_REPO_DIR% && git pull && docker build -t %IMAGE% . && (docker stop %CONTAINER% 2>/dev/null || true) && (docker rm %CONTAINER% 2>/dev/null || true) && docker run -d --restart=unless-stopped --name %CONTAINER% -p %HOST_PORT%:%CONTAINER_PORT% %IMAGE%"
if errorlevel 1 (
    echo.
    echo ECS deploy failed. Check the SSH session output above.
    exit /b 1
)

echo.
echo === [3/3] Done ===
echo Demo: http://139.224.204.231:%HOST_PORT%
echo.
endlocal
