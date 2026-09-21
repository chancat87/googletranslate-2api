#Requires -Version 5.1
# start.ps1 - googletranslate-2api 开发环境启动脚本
# 功能: 复用/创建 .venv -> 安装依赖 -> 校验 .env -> 启动 uvicorn :8088 (--reload)

$ErrorActionPreference = "Stop"

# 项目根目录: 脚本所在目录 (兼容从任意 cwd 调用)
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = (Get-Location).Path }
Set-Location $ProjectRoot

# 1) 确保 UTF-8: requirements 可能含中文注释, 否则 GBK 解码报 UnicodeDecodeError
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# 2) venv: 不存在则创建
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[start] 未找到 .venv, 正在创建 (py -3.10 -m venv .venv) ..." -ForegroundColor Yellow
    & py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[start] 创建 venv 失败, 请确认已安装 Python 3.10 (py -3.10 --version)"
        exit 1
    }
}

# 3) 安装依赖 (幂等)
Write-Host "[start] 安装/校验依赖 (pip install -r requirements-dev.txt) ..." -ForegroundColor Cyan
& $VenvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "[start] pip install 失败"
    exit 1
}

# 4) 校验 .env
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
    Write-Host "`n[WARN] 未找到 .env, 已从 .env.example 复制生成。" -ForegroundColor Yellow
    Write-Host "[WARN] 请编辑 .env, 将 GOOGLE_API_KEY 替换为真实 Key 后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}

# 占位符检查
$envContent = Get-Content -LiteralPath $EnvFile -Raw -Encoding UTF8
if ($envContent -match "在这里填入") {
    Write-Host "`n[WARN] .env 中 GOOGLE_API_KEY 仍是占位符(包含「在这里填入」)。" -ForegroundColor Yellow
    Write-Host "[WARN] 请编辑 .env 填入真实 GOOGLE_API_KEY 后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}

# 5) 启动
Write-Host "[start] 启动: python -m uvicorn main:app --reload --port 8088" -ForegroundColor Green
Write-Host "[start] 访问: http://127.0.0.1:8088  (Ctrl+C 停止)" -ForegroundColor Green
Write-Host "[start] API 文档: http://127.0.0.1:8088/docs" -ForegroundColor Cyan
Write-Host "[start] 管理面板: http://127.0.0.1:8088/admin  (需 API_MASTER_KEY)" -ForegroundColor Cyan
& $VenvPython -m uvicorn main:app --reload --port 8088
