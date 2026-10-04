@echo off
rem =====================================================
rem  蒸馏工坊一键启动
rem  检测 Python / Node.js -> 自动补齐依赖并构建界面 -> 拉起 GUI
rem  双击即可；也可带参数：启动.bat --port 9000 --no-browser
rem =====================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/4] 检查 Python ...
where python >nul 2>nul
if errorlevel 1 goto :no_python

echo [2/4] 检查 Node.js（构建界面用）...
where node >nul 2>nul
if errorlevel 1 goto :no_node

rem ------- 后端依赖：缺 flask 才装 -------
python -c "import flask, dotenv" >nul 2>nul
if errorlevel 1 (
  echo [3/4] 首次运行：安装后端依赖 ...
  python -m pip install -r requirements.txt
  if errorlevel 1 goto :pip_fail
) else (
  echo [3/4] 后端依赖已就绪
)

rem ------- 前端依赖 + 构建（gui.py 还会在源码更新时自动重建） -------
if not exist "frontend\node_modules" (
  echo [4/4] 首次运行：安装前端依赖 ...
  pushd frontend
  call npm install --no-fund --no-audit
  if errorlevel 1 goto :npm_fail
  popd
)
if not exist "gui\dist\index.html" (
  echo [4/4] 构建界面 ...
  pushd frontend
  call npm run build
  if errorlevel 1 goto :build_fail
  popd
) else (
  echo [4/4] 界面已是最新（gui.py 会在源码更新时自动重建）
)

echo.
echo [*] 启动中，浏览器会自动打开 http://127.0.0.1:8765
echo [*] 关掉这个窗口即可退出程序。
echo.
python gui.py %*
goto :end

:no_python
echo [X] 没找到 Python。请安装 Python 3.9 及以上，并在安装时勾选 "Add python.exe to PATH"。
echo     下载：https://www.python.org/downloads/
goto :fail

:no_node
echo [X] 没找到 Node.js。构建界面需要它（装一次即可）。
echo     下载：https://nodejs.org/ （选 LTS 版）
goto :fail

:pip_fail
echo [X] 后端依赖安装失败。可以手动执行：python -m pip install -r requirements.txt
goto :fail

:npm_fail
echo [X] 前端依赖安装失败。可以手动执行：cd frontend ^&^& npm install
goto :fail

:build_fail
echo [X] 界面构建失败。可以手动执行：cd frontend ^&^& npm run build
goto :fail

:fail
echo.
pause
exit /b 1

:end
endlocal
