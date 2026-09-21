#Requires -Version 5.1
# stop.ps1 - 停止监听 8088 的 googletranslate-2api 服务
# 安全策略: 只停止 8088 监听进程及其直接父进程(若父进程是运行 main:app 的 uvicorn reloader),
#           不滥杀其他进程。

$ErrorActionPreference = "SilentlyContinue"
$Port = 8088

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen
if (-not $conns) {
    Write-Host "[stop] 端口 $Port 未在监听, 无需停止。"
    exit 0
}

$stopped = @()
foreach ($c in $conns) {
    $pid_ = $c.OwningProcess
    if (-not $pid_) { continue }

    # 记录父进程, 用于清理可能残留的 uvicorn --reload 父进程
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid_"
    $parentPid = $null
    if ($proc) { $parentPid = $proc.ParentProcessId }

    Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
    Write-Host "[stop] 已停止进程 $pid_ (监听 $Port)."
    $stopped += $pid_

    # 若直接父进程是运行 uvicorn main:app 的 reloader, 一并停止 (防止其自动重启子进程)
    if ($parentPid) {
        $pp = Get-CimInstance Win32_Process -Filter "ProcessId=$parentPid"
        if ($pp -and $pp.CommandLine -match "uvicorn" -and $pp.CommandLine -match "main:app") {
            Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
            Write-Host "[stop] 已停止 uvicorn reloader 父进程 $parentPid."
            $stopped += $parentPid
        }
    }
}

# 等待端口释放并核验
$released = $false
for ($i = 0; $i -lt 5; $i++) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen)) {
        $released = $true
        break
    }
}
if ($released) {
    Write-Host "[stop] 端口 $Port 已释放。"
} else {
    Write-Host "[stop] 端口 $Port 仍未释放, 请确认是否有其他程序占用。"
}
exit 0
