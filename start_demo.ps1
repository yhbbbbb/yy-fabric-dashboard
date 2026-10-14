$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:YY_DASHBOARD_HOST = "0.0.0.0"
$env:YY_DASHBOARD_PORT = "8765"
python scripts\build_demo_db.py
python scripts\init_admin_db.py
python backend\server.py
