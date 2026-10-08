# Запуск юнит-тестов интеграции Akvilon InHome (Windows-обёртка WSL).
# Использование:
#   scripts/run_tests.ps1             # полный прогон
#   scripts/run_tests.ps1 -Test "tests/test_protocol.py"
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$TestArg = if ($args.Count -gt 0) { $args -join " " } else { "tests" }

if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
    Write-Host "Ошибка: WSL не установлен. Нужен WSL с развёрнутым python3+pip." -Foreground Red
    exit 1
}

# 1) Убедиться, что WSL-venv с pytest существует
$keepalive = "if [ -x /tmp/akv_test_venv/bin/python ]; then echo VENV_OK; else echo NO_VENV; fi"
$venvState = wsl -e bash -c $keepalive 2>&1 | Select-Object -Last 1
if ($venvState -ne "VENV_OK") {
    Write-Host ">> venv не найден, создаю..." -Foreground Yellow
    $drive = $root.Substring(0, 1).ToLower()
    $setuppath = "/mnt/$drive$($root.Substring(3).Replace('\','/'))/scripts/setup_test_env.sh"
    wsl -e bash $setuppath
}

# 2) Запуск pytest внутри WSL (Windows C:\ -> /mnt/c/)
$noColon = $root.Replace(':', '')
$drive = $noColon.Substring(0, 1).ToLower()
$wslPath = "/mnt/$drive$($noColon.Substring(1).Replace('\','/'))"
wsl -e bash -c "cd $wslPath && /tmp/akv_test_venv/bin/python -m pytest $TestArg -q"
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ">>> ТЕСТЫ НЕ ПРОШЛИ (код $code). Слияние/пуш заблокирован." -Foreground Red
}
exit $code