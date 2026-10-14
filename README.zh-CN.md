# YY 面料用量追溯分析看板

[English README](README.md)

这是一个面料用量追溯与经营分析看板的脱敏演示项目，围绕 `Quotation -> PPO -> Bulk` 三个业务阶段，展示订单串联、YY 对比、损耗分析、交付趋势和数据质量管理。

仓库只包含应用代码、测试代码和合成演示数据生成脚本，不包含公司的原始 Excel、客户资料、工厂资料、真实订单或生产数据库。

## 主要功能

- Quotation、PPO、Bulk 三阶段订单分析
- Bulk -> PPO -> Quotation 链路状态和订单查询
- 客户、工厂、款式、Garment Feature、日期等筛选
- QUO YY、PPO YY、Bulk YY 及阶段差异分析
- 损耗、节省码数、完成时长和数据质量分析
- 客户、工厂、部门和 Creator 排行
- 订单趋势、交付趋势和异常数据查看
- 基于角色的页面和操作权限
- 超级管理员用户、角色和权限管理
- 适配桌面端和移动端

## 技术栈

- Python 标准库 HTTP Server
- SQLite
- 原生 HTML、CSS、JavaScript
- Python `unittest`

## 本地运行

需要 Python 3.10 或更高版本。在项目根目录执行：

```powershell
$env:YY_ADMIN_PASSWORD = "请设置本地管理员密码"
python scripts\build_demo_db.py
python scripts\init_admin_db.py
python backend\server.py
```

打开 `http://127.0.0.1:8765` 即可访问。

首次初始化的管理员用户名为 `admin`。管理员密码通过环境变量 `YY_ADMIN_PASSWORD` 设置，不会写入仓库。

## 局域网访问

如需让同一局域网内的用户访问：

```powershell
$env:YY_DASHBOARD_HOST = "0.0.0.0"
$env:YY_DASHBOARD_PORT = "8765"
python scripts\build_demo_db.py
python scripts\init_admin_db.py
python backend\server.py
```

如果 Windows 防火墙拦截访问，可用管理员权限运行 `allow_lan_firewall.ps1`。

## 数据说明

`scripts\build_demo_db.py` 会生成少量合成数据到 `data/`，用于演示看板功能。数据库文件已被 Git 忽略，不会上传到 GitHub。

实际业务数据应在公司内部环境中完成清洗、入库和匹配，禁止将真实 Excel、CSV、Pickle、SQLite、截图、导出文件或客户信息放入本仓库。

## 测试

运行项目测试：

```powershell
py -3.11 -m unittest discover -s tests -v
```

项目当前包含权限、路由、前端权限显示和公开仓库安全检查。
