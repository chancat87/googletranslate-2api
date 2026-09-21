<#
.SYNOPSIS
  刷新真实 curl 输出附录 (docs/curl_appendix.md)。
.DESCRIPTION
  需要有效 GOOGLE_API_KEYS（拒绝占位符）。流程:
  启动 uvicorn -> 跑真实 curl 序列 -> 写 docs/curl_appendix.md -> 停服。
  幂等: 重复运行覆盖旧附录; 中途失败会停服。
.EXAMPLE
  $env:GOOGLE_API_KEYS="AIza..." ; .\scripts\refresh_curl_appendix.ps1
#>
$ErrorActionPreference = "Stop"
$port = 8094
$base = "http://127.0.0.1:$port"
$outPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\docs\curl_appendix.md"))

$key = @($env:GOOGLE_API_KEYS, $env:GOOGLE_API_KEY) | Where-Object { $_ } | Select-Object -First 1
if (-not $key -or $key -match "在这里填入") {
    throw "需要有效 GOOGLE_API_KEYS / GOOGLE_API_KEY (拒绝占位符)"
}

Write-Host "启动 uvicorn :$port ..."
$env:PYTHONUTF8 = "1"
$proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","main:app","--port","$port" -WorkingDirectory (Get-Location) -PassThru -WindowStyle Hidden
try {
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest -Uri "$base/health" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw "uvicorn 未就绪" }

    $lines = @()
    $lines += "# 真实调用输出附录（curl 实跑，非编造）"
    $lines += ""
    $lines += "> 生成: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | 命令: scripts/refresh_curl_appendix.ps1 | 基址: $base"

    function Add-Block($title, [string]$cmd, [string]$out) {
        $script:lines += ""
        $script:lines += "## $title"
        $script:lines += '```bash'
        $script:lines += $cmd
        $script:lines += '```'
        $script:lines += '```'
        $script:lines += ($out -replace 'Bearer [A-Za-z0-9_\-\.]+', 'Bearer <MASKED>')
        $script:lines += '```'
    }

    # 请求体用单引号 PowerShell 变量（字面 JSON），展示与执行共用同一份
    $bodyNS  = '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
    $bodyST  = '{"messages":[{"role":"user","content":"Good morning"}],"target_lang":"zh-CN","stream":true}'
    $bodyBatch = '{"texts":["apple","banana"],"target_lang":"zh-CN"}'
    $bodyDetect = '{"text":"hello world"}'

    $cmdNS = "curl -s -X POST $base/v1/chat/completions -H 'Content-Type: application/json' -d '" + $bodyNS + "'"
    Add-Block "非流式翻译" $cmdNS (curl.exe -s -X POST "$base/v1/chat/completions" -H 'Content-Type: application/json' -d $bodyNS)

    $cmdST = "curl -s -N -X POST $base/v1/chat/completions -H 'Content-Type: application/json' -d '" + $bodyST + "'"
    Add-Block "流式翻译" $cmdST (curl.exe -s -N -X POST "$base/v1/chat/completions" -H 'Content-Type: application/json' -d $bodyST)

    $cmdBatch = "curl -s -X POST $base/v1/translate/batch -H 'Content-Type: application/json' -d '" + $bodyBatch + "'"
    Add-Block "批量翻译" $cmdBatch (curl.exe -s -X POST "$base/v1/translate/batch" -H 'Content-Type: application/json' -d $bodyBatch)

    $cmdDetect = "curl -s -X POST $base/v1/translate/detect -H 'Content-Type: application/json' -d '" + $bodyDetect + "'"
    Add-Block "语言检测" $cmdDetect (curl.exe -s -X POST "$base/v1/translate/detect" -H 'Content-Type: application/json' -d $bodyDetect)

    Add-Block "health" "curl -s $base/health" (curl.exe -s "$base/health")

    $lines -join "`n" | Set-Content -LiteralPath $outPath -Encoding utf8NoBOM
    Write-Host "已生成 $outPath"
}
finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    Write-Host "已停服"
}
