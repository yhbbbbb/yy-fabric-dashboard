$port = 8765
$ruleName = "YY Fabric Dashboard $port"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    Write-Error "Please run PowerShell as Administrator, then run this script again."
    exit 1
}

if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $port `
        -Action Allow `
        -Profile Private
    Write-Host "Firewall rule created for TCP port $port on the Private profile."
} else {
    Write-Host "Firewall rule already exists: $ruleName"
}
