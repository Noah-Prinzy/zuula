# Delegate a task to Jason (OpenCode agent, Mistral).
# Usage: powershell -File .opencode/jason.ps1 "Write a test for ..."
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Task)

$cli = Get-ChildItem "$env:APPDATA\ai.opencode.desktop\cli\*\opencode-cli.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $cli) { Write-Error "OpenCode desktop CLI not found under $env:APPDATA\ai.opencode.desktop\cli"; exit 1 }

Set-Location (Split-Path $PSScriptRoot -Parent)
& $cli.FullName run --agent jason --title "Jason: $($Task[0].Substring(0, [Math]::Min(50, $Task[0].Length)))" ($Task -join ' ')
exit $LASTEXITCODE
