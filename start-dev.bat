@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem googletranslate-2api 开发启动脚本 (Windows)
rem 功能: 复用/创建 .venv -> 安装依赖 -> 校验 .env -> 启动 uvicorn :8088
rem ============================================================

rem 切换到脚本所在目录 (支持从任意路径调用)
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem ---------- 1) 检查/创建 venv ----------
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo [start] 未找到 .venv, 正在用 Python 3.10 创建...
py -3.10 -m venv ".venv"
if errorlevel 1 goto :err_venv
echo [start] venv 创建完成.

:venv_ok
set "VENV_PY=.venv\Scripts\python.exe"

rem ---------- 2) 安装依赖 (幂等) ----------
echo [start] 安装/校验依赖 requirements-dev.txt ...
"%VENV_PY%" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :err_pip

rem ---------- 3) 校验 .env ----------
if exist ".env" goto :env_check
echo [WARN] 未找到 .env, 已从 .env.example 复制生成.
copy /y ".env.example" ".env" >nul
echo [WARN] 请编辑 .env, 填入真实 GOOGLE_API_KEY 后重新运行本脚本.
exit /b 1

:env_check
findstr /C:"在这里填入" ".env" >nul && goto :err_env_placeholder
goto :launch

:err_venv
echo [ERROR] 创建 venv 失败, 请确认已安装 Python 3.10 (py -3.10 --version).
exit /b 1

:err_pip
echo [ERROR] pip install 失败, 请检查网络或 requirements-dev.txt.
exit /b 1

:err_env_placeholder
echo [WARN] .env 中 GOOGLE_API_KEY 仍是占位符 (包含「在这里填入」).
echo [WARN] 请编辑 .env 填入真实 GOOGLE_API_KEY 后重新运行本脚本.
exit /b 1

:launch
echo [start] 启动: python -m uvicorn main:app --reload --port 8088
echo [start] 访问: http://127.0.0.1:8088   (Ctrl+C 停止)
echo [start] API 文档: http://127.0.0.1:8088/docs
echo [start] 管理面板: http://127.0.0.1:8088/admin   (需 API_MASTER_KEY)
"%VENV_PY%" -m uvicorn main:app --reload --port 8088
