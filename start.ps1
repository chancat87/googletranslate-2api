#Requires -Version 5.1
# start.ps1 - googletranslate-2api 开发环境启动脚本
# 功能: 复用/创建 .venv -> 安装依赖 -> 校验 .env
#       -> 无 Key 自动 DEMO_MODE -> 启动 uvicorn :8088 (--reload)
#       -> 服务就绪后自动打开 Web UI

$ErrorActionPreference = "Stop"

# 项目根目录: 脚本所在目录 (兼容从任意 cwd 调用)
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = (Get-Location).Path }
Set-Location $ProjectRoot

# 1) 确保 UTF-8: requirements 可能含中文注释, 否则 GBK 解码报 UnicodeDecodeError
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$AppUrl = "http://127.0.0.1:8088"

Write-Host ""
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |   googletranslate-2api   Dev Server                      |" -ForegroundColor Cyan
Write-Host "  |   Google Translate  ->  OpenAI 兼容 API 代理             |" -ForegroundColor Cyan
Write-Host "  |   $AppUrl" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# 2) venv: 不存在则创建
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[start] 未找到 .venv, 正在创建 (py -3.10 -m venv .venv) ..." -ForegroundColor Yellow
    & py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 创建 venv 失败, 请确认已安装 Python 3.10 (py -3.10 --version)" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
}

# 3) 安装依赖 (幂等)
Write-Host "[start] 安装/校验依赖 (pip install -r requirements-dev.txt) ..." -ForegroundColor Cyan
& $VenvPython -m pip install -r requirements-dev.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install 失败, 请检查网络或 requirements-dev.txt" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

# 4) 校验 .env: 缺失/占位时自动进入 DEMO_MODE, 不再阻塞启动
$EnvFile = Join-Path $ProjectRoot ".env"
$DemoMode = $false
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
    Write-Host "[WARN] 未找到 .env, 已从 .env.example 复制生成。" -ForegroundColor Yellow
    $DemoMode = $true
} elseif ((Get-Content -LiteralPath $EnvFile -Raw -Encoding UTF8) -match "在这里填入") {
    Write-Host "[WARN] .env 中的 GOOGLE_API_KEY 仍是占位符。" -ForegroundColor Yellow
    $DemoMode = $true
}
if ($DemoMode) {
    $env:DEMO_MODE = "1"
    Write-Host "[INFO] 已自动启用 DEMO_MODE=true (无 Key 演示模式, 可直接体验 Web UI)。" -ForegroundColor Green
    Write-Host "[INFO] 填入真实 Key 后删除 DEMO_MODE 或设为 false 即可使用真实翻译。" -ForegroundColor Green
}

# 5) 后台等待服务就绪, 就绪后自动打开浏览器
$BrowserJob = Start-Job -ScriptBlock {
    param($Url)
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$Url/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) {
                Start-Process $Url
                break
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
} -ArgumentList $AppUrl

# 6) 启动
Write-Host ""
Write-Host "[start] 后台等待服务就绪, 就绪后自动打开浏览器..." -ForegroundColor DarkGray
Write-Host "[start] 启动: python -m uvicorn main:app --reload --port 8088" -ForegroundColor Green
Write-Host "[start] 访问: $AppUrl   (Ctrl+C 停止)" -ForegroundColor Green
Write-Host "[start] 文档: $AppUrl/docs" -ForegroundColor Cyan
Write-Host "[start] 面板: $AppUrl/admin   (需 API_MASTER_KEY)" -ForegroundColor Cyan
Write-Host ""

try {
    & $VenvPython -m uvicorn main:app --reload --port 8088
} finally {
    Remove-Job -Job $BrowserJob -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "[start] 服务已停止. 再见!" -ForegroundColor Cyan
Write-Host ""
