#Requires -Version 5.1
# stop.ps1 - 停止监听 8088 的 googletranslate-2api 服务 (含 uvicorn --reload 整进程树)
# 安全策略: 只终止 8088 监听进程及其子进程树, 以及(若存在)其 uvicorn reloader 父进程树,
#           不滥杀其他进程。

$ErrorActionPreference = "SilentlyContinue"
$Port = 8088
$stopped = @()

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen
if (-not $conns) {
    Write-Host "[stop] 端口 $Port 未在监听, 无需停止。"
    exit 0
}

foreach ($c in $conns) {
    $pid_ = $c.OwningProcess
    if (-not $pid_) { continue }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid_"
    $parentPid = $null
    if ($proc) { $parentPid = $proc.ParentProcessId }

    # 整树终止: Windows 上 uvicorn --reload 由 reloader 父进程持有监听 socket,
    # spawn 的 worker 子进程继承该 socket; 只杀监听者会遗留 worker 占住端口。
    taskkill /PID $pid_ /T /F | Out-Null
    Write-Host "[stop] 已终止进程树 $pid_ (监听 $Port)."
    $stopped += $pid_

    if ($parentPid) {
        $pp = Get-CimInstance Win32_Process -Filter "ProcessId=$parentPid"
        if ($pp -and $pp.CommandLine -match "uvicorn" -and $pp.CommandLine -match "main:app") {
            taskkill /PID $parentPid /T /F | Out-Null
            Write-Host "[stop] 已终止 uvicorn reloader 父进程树 $parentPid."
            $stopped += $parentPid
        }
    }
}

# 等待端口释放并核验
$released = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $released = $true
        break
    }
}
if ($released) {
    Write-Host "[stop] 端口 $Port 已释放。"
} else {
    Write-Host "[stop] 端口 $Port 仍未释放, 当前相关监听/连接:"
    netstat -ano | Select-String ":8088" | Select-Object -First 5
}
exit 0
