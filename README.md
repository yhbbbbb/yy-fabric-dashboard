# YY Fabric Intelligence Dashboard

This repository is a sanitized portfolio demo for a fabric-usage traceability dashboard.
It contains application code and synthetic data generation only. It does not contain
company source files, customer data, factory data, order data, or production databases.

## Features

- Quotation, PPO, and Bulk order-stage analysis
- Bulk -> PPO -> Quotation traceability states
- Customer, factory, style, and date filters
- YY variance, wastage, completion duration, and data-quality analysis
- Order lookup with chain details
- Role-based page permissions and a super-admin management page
- Responsive desktop and mobile layout

## Technology

- Python standard library HTTP server
- SQLite
- Vanilla HTML, CSS, and JavaScript
- Python `unittest`

## Run Locally

Use Python 3.10 or newer.

```powershell
$env:YY_ADMIN_PASSWORD = "choose-a-local-password"
python scripts\build_demo_db.py
python scripts\init_admin_db.py
python backend\server.py
```

Open `http://127.0.0.1:8765`.

The build script creates a small synthetic database under `data/`. Database files
are ignored by Git and are intentionally not included in this repository.

## LAN Access

Set the host before starting the server:

```powershell
$env:YY_DASHBOARD_HOST = "0.0.0.0"
$env:YY_DASHBOARD_PORT = "8765"
python scripts\build_demo_db.py
python scripts\init_admin_db.py
python backend\server.py
```

For Windows, run `allow_lan_firewall.ps1` as an administrator if the firewall
blocks inbound access.

## Demo Account

The initial administrator username is `admin`. The password is never stored in
the repository; set it through `YY_ADMIN_PASSWORD` before the first initialization.
Change it before sharing a running demo with other users.

## Data Safety

Do not place real Excel, CSV, Pickle, SQLite, screenshots, exports, or customer
information in this repository. Use the private company environment for actual
data processing.
