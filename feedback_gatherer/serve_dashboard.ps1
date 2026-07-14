# Runs the dashboard while holding a Windows power request so the laptop never
# enters Modern Standby / display-off idle (which suspends the network and cuts
# colleagues off). The request is scoped to this window: close it, and normal
# power behaviour returns automatically.
$ErrorActionPreference = "Continue"

Add-Type -Name Power -Namespace Win32 -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED (0x80000003).
# Note: converted from a hex string because PowerShell 5.1 parses the literal
# 0x80000003 as a negative Int32, which cannot cast to the API's UInt32.
$flags = [Convert]::ToUInt32("80000003", 16)
$prev = [Win32.Power]::SetThreadExecutionState($flags)
if ($prev -eq 0) {
    Write-Warning "Could not set keep-awake state - the laptop may still idle."
} else {
    Write-Host "  Keep-awake active: the laptop will not sleep or idle while this window is open." -ForegroundColor Green
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m streamlit run feedback_gatherer\dashboard.py --server.port 8501
