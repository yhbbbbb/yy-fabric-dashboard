from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import socket
import statistics
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from . import admin_auth
except ImportError:
    import admin_auth


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "dashboard.sqlite"
FRONTEND = ROOT / "frontend"
CACHE_LIMIT = 96
HOST = os.environ.get("YY_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("YY_DASHBOARD_PORT", "8765"))
_response_cache: dict[tuple, tuple[tuple[int, int], object]] = {}
_response_cache_lock = threading.Lock()
_response_cache_signature: tuple[int, int] | None = None
PAGE_PERMISSIONS = {
    "/api/summary": "overview",
    "/api/trend": "overview",
    "/api/rankings": "overview",
    "/api/analytics": "analytics",
    "/api/orders": "orders",
    "/api/chain": "chain",
    "/api/data-quality": "quality",
}
BUSINESS_PERMISSIONS = tuple(PAGE_PERMISSIONS.values())


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -65536")
    conn.execute("PRAGMA mmap_size = 268435456")
    return conn


def rows_to_dict(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def qvalue(params: dict[str, list[str]], key: str) -> str:
    return params.get(key, [""])[0].strip()


def db_signature() -> tuple[int, int]:
    stat = DB_PATH.stat()
    return stat.st_mtime_ns, stat.st_size


def cached_response(name: str, params: dict[str, list[str]], producer):
    global _response_cache_signature
    signature = db_signature()
    normalized = tuple(sorted((key, tuple(values)) for key, values in params.items()))
    key = (name, normalized)
    with _response_cache_lock:
        if _response_cache_signature != signature:
            _response_cache.clear()
            _response_cache_signature = signature
        cached = _response_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    result = producer()
    with _response_cache_lock:
        if _response_cache_signature == signature:
            if len(_response_cache) >= CACHE_LIMIT:
                _response_cache.pop(next(iter(_response_cache)))
            _response_cache[key] = (signature, result)
    return result


def filtered_bulk(conn: sqlite3.Connection, params: dict[str, list[str]]) -> tuple[str, list[object]]:
    where = ["1=1"]
    values: list[object] = []
    scope = qvalue(params, "scope") or "main"
    if scope == "main":
        where.append("analysis_scope = 'main'")
    elif scope == "all":
        pass
    else:
        where.append("analysis_scope = ?")
        values.append(scope)
    for field, param in [("buyer", "buyer"), ("fabric_source", "fabric_source"), ("chain_state", "chain_state")]:
        value = qvalue(params, param)
        if value:
            where.append(f"{field} = ?")
            values.append(value)
    customer = qvalue(params, "customer")
    if customer:
        where.append("buyer = ?")
        values.append(customer)
    factory = qvalue(params, "factory")
    if factory:
        where.append(
            "EXISTS (SELECT 1 FROM bulk_detail bd_filter WHERE bd_filter.garment_order = bulk_order.garment_order AND bd_filter.factory_code = ?)"
        )
        values.append(factory)
    style = qvalue(params, "style")
    if style:
        where.append(
            "EXISTS (SELECT 1 FROM bulk_detail bd_filter WHERE bd_filter.garment_order = bulk_order.garment_order AND bd_filter.style_description = ?)"
        )
        values.append(style)
    garment_feature = qvalue(params, "garment_feature")
    if garment_feature:
        where.append(
            "EXISTS (SELECT 1 FROM bulk_detail bd_filter WHERE bd_filter.garment_order = bulk_order.garment_order AND bd_filter.garment_feature = ?)"
        )
        values.append(garment_feature)
    value = qvalue(params, "from")
    if value:
        where.append("delivery_date >= ?")
        values.append(value)
    value = qvalue(params, "to")
    if value:
        where.append("delivery_date <= ?")
        values.append(value)
    return " AND ".join(where), values


def filtered_workflow(
    conn: sqlite3.Connection,
    params: dict[str, list[str]],
    stage: str | None = None,
    date_field: str = "submitted_at",
) -> tuple[str, list[object]]:
    where = ["1=1"]
    values: list[object] = []
    if stage:
        where.append("stage = ?")
        values.append(stage)
    for field, param in [
        ("customer_name", "customer"),
        ("factory_cd", "factory"),
        ("style_no", "style"),
        ("creator", "creator"),
        ("creator_dept", "creator_dept"),
    ]:
        value = qvalue(params, param)
        if value:
            where.append(f"{field} = ?")
            values.append(value)
    garment_feature = qvalue(params, "garment_feature")
    if garment_feature:
        where.append(
            "EXISTS (SELECT 1 FROM chain_detail cd_filter JOIN bulk_detail bd_filter ON bd_filter.garment_order = cd_filter.garment_order WHERE cd_filter.ppo_workflow_no = workflow_order.workflow_no AND bd_filter.garment_feature = ?)"
        )
        values.append(garment_feature)
    start = qvalue(params, "from")
    end = qvalue(params, "to")
    if start:
        where.append(f"{date_field} >= ?")
        values.append(start)
    if end:
        where.append(f"{date_field} <= ?")
        values.append(f"{end} 23:59:59")
    return " AND ".join(where), values


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (index - lower), 2)


def next_month_key(month_key: str) -> str:
    year, month = (int(value) for value in month_key.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def duration_stats(conn: sqlite3.Connection, params: dict[str, list[str]], stage: str) -> dict:
    where, values = filtered_workflow(conn, params, stage, "submitted_at")
    rows = conn.execute(
        f"SELECT duration_hours FROM workflow_order WHERE {where} AND duration_hours IS NOT NULL AND duration_hours BETWEEN 0 AND 720",
        values,
    ).fetchall()
    nums = [float(row[0]) for row in rows]
    return {
        "stage": stage,
        "count": len(nums),
        "avg_hours": round(statistics.mean(nums), 2) if nums else None,
        "median_hours": round(statistics.median(nums), 2) if nums else None,
        "p90_hours": percentile(nums, 0.9),
    }


def valid_workflow_yy(column: str) -> str:
    return f"{column} IS NOT NULL AND {column} > 0 AND {column} <= 20"


def valid_bulk_number(column: str) -> str:
    return f"{column} IS NOT NULL AND {column} >= 0"


def valid_bulk_yy(column: str) -> str:
    return f"{column} IS NOT NULL AND {column} > 0 AND {column} <= 20"


def summary(params: dict[str, list[str]]) -> dict:
    conn = db()
    where, values = filtered_bulk(conn, params)
    bulk_counts = conn.execute(
        f"""
        SELECT COUNT(*) total,
               SUM(CASE WHEN ppo_workflow_no IS NOT NULL THEN 1 ELSE 0 END) matched,
               SUM(CASE WHEN chain_state = 'full_chain' THEN 1 ELSE 0 END) full_chain,
               SUM(CASE WHEN delivery_date_status = 'valid' THEN 1 ELSE 0 END) delivery_valid,
               SUM(CASE WHEN delivery_date_status != 'valid' THEN 1 ELSE 0 END) delivery_dq,
               SUM(CASE WHEN is_outside = 1 THEN 1 ELSE 0 END) outside_orders
        FROM bulk_order
        WHERE {where}
        """,
        values,
    ).fetchone()
    total = int(bulk_counts["total"] or 0)
    matched = int(bulk_counts["matched"] or 0)
    full = int(bulk_counts["full_chain"] or 0)
    delivery_valid = int(bulk_counts["delivery_valid"] or 0)
    dq = int(bulk_counts["delivery_dq"] or 0)
    outside = int(bulk_counts["outside_orders"] or 0)
    workflow_filters = {}
    for key in ("customer", "factory", "style", "creator", "creator_dept", "from", "to"):
        if qvalue(params, key):
            workflow_filters[key] = params[key]
    workflow_where, workflow_values = filtered_workflow(conn, workflow_filters)
    workflow_counts = conn.execute(
        f"""
        SELECT
          SUM(CASE WHEN stage='QUO' AND submitted_at IS NOT NULL THEN 1 ELSE 0 END) quo_submitted,
          SUM(CASE WHEN stage='QUO' AND completed_at IS NOT NULL THEN 1 ELSE 0 END) quo_completed,
          SUM(CASE WHEN stage='PPO' AND submitted_at IS NOT NULL THEN 1 ELSE 0 END) ppo_submitted,
          SUM(CASE WHEN stage='PPO' AND completed_at IS NOT NULL THEN 1 ELSE 0 END) ppo_completed
        FROM workflow_order
        WHERE {workflow_where}
        """,
        workflow_values,
    ).fetchone()
    latest = conn.execute(
        "SELECT MAX(max_date) FROM (SELECT MAX(submitted_at) max_date FROM workflow_order UNION ALL SELECT MAX(delivery_date) FROM bulk_order)"
    ).fetchone()[0]
    states = rows_to_dict(
        conn.execute(
            f"SELECT COALESCE(chain_state, 'unknown') state, COUNT(*) count FROM bulk_order WHERE {where} GROUP BY chain_state ORDER BY count DESC",
            values,
        ).fetchall()
    )
    conn.close()
    return {
        "bulk_orders": total,
        "bulk_ppo_matched": matched,
        "bulk_ppo_rate": round(matched / total * 100, 2) if total else 0,
        "full_chain": full,
        "full_chain_rate": round(full / total * 100, 2) if total else 0,
        "valid_delivery": delivery_valid,
        "delivery_quality_rate": round(delivery_valid / total * 100, 2) if total else 0,
        "delivery_dq": dq,
        "quo_submitted": int(workflow_counts["quo_submitted"] or 0),
        "quo_completed": int(workflow_counts["quo_completed"] or 0),
        "ppo_submitted": int(workflow_counts["ppo_submitted"] or 0),
        "ppo_completed": int(workflow_counts["ppo_completed"] or 0),
        "outside_orders": outside,
        "latest_available_date": latest,
        "yy_metrics_available": True,
        "yy_metrics_note": "YY、Marker YY、利用率和损耗字段已从原始三阶段文件入库；三阶段差异仅在有严格链路的样本中计算。",
        "states": states,
    }


def trend(params: dict[str, list[str]]) -> dict:
    conn = db()
    granularity = qvalue(params, "granularity") or "year"
    if granularity == "day":
        bucket = "substr(submitted_at, 1, 10)"
        bulk_bucket = "substr(delivery_date, 1, 10)"
    elif granularity == "month":
        bucket = "substr(submitted_at, 1, 7)"
        bulk_bucket = "substr(delivery_date, 1, 7)"
    else:
        bucket = "substr(submitted_at, 1, 4)"
        bulk_bucket = "substr(delivery_date, 1, 4)"
    workflow_where, workflow_values = filtered_workflow(conn, params)
    bulk_where, bulk_values = filtered_bulk(conn, params)
    stage_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT {bucket} period,
                   SUM(CASE WHEN stage='QUO' AND submitted_at IS NOT NULL THEN 1 ELSE 0 END) quo_submitted,
                   SUM(CASE WHEN stage='QUO' AND completed_at IS NOT NULL THEN 1 ELSE 0 END) quo_completed,
                   SUM(CASE WHEN stage='PPO' AND submitted_at IS NOT NULL THEN 1 ELSE 0 END) ppo_submitted,
                   SUM(CASE WHEN stage='PPO' AND completed_at IS NOT NULL THEN 1 ELSE 0 END) ppo_completed
            FROM workflow_order
            WHERE {workflow_where}
              AND period IS NOT NULL
              AND submitted_at >= '2019-01-01'
              AND submitted_at < '2027-01-01'
            GROUP BY period
            ORDER BY period
            """,
            workflow_values,
        ).fetchall()
    )
    bulk_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT {bulk_bucket} period, COUNT(*) bulk_orders,
                   SUM(CASE WHEN delivery_date_status='valid' THEN 1 ELSE 0 END) valid_delivery
            FROM bulk_order
            WHERE {bulk_where}
              AND delivery_date IS NOT NULL
              AND delivery_date_status='valid'
              AND delivery_date >= '2019-01-01'
              AND delivery_date < '2027-01-01'
            GROUP BY period
            ORDER BY period
            """,
            bulk_values,
        ).fetchall()
    )
    conn.close()
    return {"granularity": granularity, "stage": stage_rows, "bulk": bulk_rows, "point_count": len(stage_rows)}


def rankings(params: dict[str, list[str]]) -> dict:
    conn = db()
    where, values = filtered_bulk(conn, params)
    buyer_rows = rows_to_dict(
        conn.execute(
            f"SELECT COALESCE(buyer,'未填写') name, COUNT(*) count FROM bulk_order WHERE {where} GROUP BY buyer ORDER BY count DESC LIMIT 500",
            values,
        ).fetchall()
    )
    state_rows = rows_to_dict(
        conn.execute(
            f"SELECT COALESCE(chain_state,'unknown') name, COUNT(*) count FROM bulk_order WHERE {where} GROUP BY chain_state ORDER BY count DESC",
            values,
        ).fetchall()
    )
    factory_rows = rows_to_dict(
        conn.execute(
            """
            SELECT COALESCE(factory_code, '未填写') name, COUNT(DISTINCT garment_order) count
            FROM bulk_detail
            GROUP BY factory_code
            ORDER BY count DESC
            LIMIT 8
            """
        ).fetchall()
    )
    style_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT COALESCE(style_description, '未填写') name, COUNT(DISTINCT garment_order) count
            FROM bulk_detail
            WHERE garment_order IN (SELECT garment_order FROM bulk_order WHERE {where})
            GROUP BY style_description
            ORDER BY count DESC
            LIMIT 10
            """,
            values,
        ).fetchall()
    )
    conn.close()
    return {"buyers": buyer_rows, "states": state_rows, "styles": style_rows, "factories": factory_rows}


def analytics(params: dict[str, list[str]]) -> dict:
    conn = db()
    bulk_where, bulk_values = filtered_bulk(conn, params)
    workflow_where, workflow_values = filtered_workflow(conn, params)
    customer_bulk = rows_to_dict(
        conn.execute(
            f"""
            SELECT COALESCE(buyer, '未填写') name,
                   COUNT(DISTINCT garment_order) order_count,
                   COALESCE(SUM(order_quantity), 0) order_pieces,
                   COALESCE(SUM(cutting_wastage_yds), 0) wastage_yds,
                   COALESCE(SUM(leftover_fabric), 0) leftover_yds
            FROM bulk_order
            WHERE {bulk_where}
            GROUP BY buyer
            """,
            bulk_values,
        ).fetchall()
    )
    customer_workflow = rows_to_dict(
        conn.execute(
            f"""
            SELECT COALESCE(
                       CASE WHEN instr(customer_name, ' (') > 0
                            THEN substr(customer_name, 1, instr(customer_name, ' (') - 1)
                            ELSE customer_name END,
                       '未填写'
                   ) name,
                   COUNT(DISTINCT CASE WHEN stage='QUO' THEN workflow_no END) quo_count,
                   COUNT(DISTINCT CASE WHEN stage='PPO' THEN workflow_no END) ppo_count
            FROM workflow_order
            WHERE {workflow_where}
            GROUP BY customer_name
            """,
            workflow_values,
        ).fetchall()
    )
    customer_chain = rows_to_dict(
        conn.execute(
            f"""
            SELECT COALESCE(buyer, '未填写') name,
                   AVG(yy_variance_ppo_bulk) yy_delta,
                   SUM(estimated_saved_yds) estimated_saved_yds
            FROM chain_detail
            WHERE chain_state='full_chain'
              AND garment_order IN (SELECT garment_order FROM bulk_order WHERE {bulk_where})
              AND yy_variance_ppo_bulk IS NOT NULL
            GROUP BY buyer
            """,
            bulk_values,
        ).fetchall()
    )
    repeat_rows = conn.execute(
        f"""
        SELECT buyer, COUNT(DISTINCT garment_order) order_count
        FROM bulk_order WHERE {bulk_where}
        GROUP BY buyer
        """,
        bulk_values,
    ).fetchall()
    repeat_map = {row[0]: row[1] for row in repeat_rows}
    workflow_map = {row["name"]: row for row in customer_workflow}
    chain_map = {row["name"]: row for row in customer_chain}
    customer_rows = []
    for row in customer_bulk:
        wf = workflow_map.get(row["name"], {})
        ch = chain_map.get(row["name"], {})
        order_count = int(row["order_count"] or 0)
        repeat_rate = round(max(order_count - 1, 0) / order_count * 100, 2) if order_count else 0
        quo_count = int(wf.get("quo_count") or 0)
        ppo_count = int(wf.get("ppo_count") or 0)
        customer_rows.append(
            {
                **row,
                "deal_rate": round(ppo_count / quo_count * 100, 2) if quo_count else None,
                "rebuy_rate": repeat_rate,
                "quo_count": quo_count,
                "ppo_count": ppo_count,
                "yy_delta": ch.get("yy_delta"),
                "estimated_saved_yds": ch.get("estimated_saved_yds"),
            }
        )
    customer_rows.sort(key=lambda item: item["order_count"], reverse=True)

    duration = {
        "quo": duration_stats(conn, params, "QUO"),
        "ppo": duration_stats(conn, params, "PPO"),
    }
    rank_specs = [
        ("factory", "factory_cd", "工厂"),
        ("creator_dept", "creator_dept", "部门"),
        ("creator", "creator", "Creator"),
    ]
    entity_rankings = {}
    for key, column, _ in rank_specs:
        entity_rankings[key] = rows_to_dict(
            conn.execute(
                f"""
                SELECT COALESCE({column}, '未填写') name,
                       COUNT(DISTINCT workflow_no) workflow_count,
                       ROUND(AVG(duration_hours), 2) avg_duration_hours,
                       ROUND(AVG(final_yy), 4) avg_yy
                FROM workflow_order
                WHERE {workflow_where}
                GROUP BY {column}
                ORDER BY workflow_count DESC
                LIMIT 15
                """,
                workflow_values,
            ).fetchall()
        )
    timeout_hours = float(qvalue(params, "timeout_hours") or "48")
    timeout_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT workflow_no, stage, customer_name, factory_cd, creator, creator_dept,
                   style_no, submitted_at, completed_at, ROUND(duration_hours, 2) duration_hours
            FROM workflow_order
            WHERE {workflow_where}
              AND duration_hours > ?
            ORDER BY duration_hours DESC
            LIMIT 100
            """,
            [*workflow_values, timeout_hours],
        ).fetchall()
    )
    yy_stage = rows_to_dict(
        conn.execute(
            f"""
            SELECT stage, COUNT(DISTINCT workflow_no) sample_count,
                   ROUND(AVG(final_yy), 4) avg_yy,
                   ROUND(AVG(marker_yy), 4) avg_marker_yy,
                   ROUND(AVG(marker_mu), 2) avg_marker_mu,
                   ROUND(AVG(weighted_mu), 2) avg_weighted_mu
            FROM workflow_order
            WHERE {workflow_where} AND final_yy IS NOT NULL
            GROUP BY stage
            """,
            workflow_values,
        ).fetchall()
    )
    bulk_yy = conn.execute(
        f"""
        SELECT COUNT(*) sample_count,
               ROUND(AVG(bulk_marker_yy), 4) avg_yy,
               ROUND(AVG(marker_utilization), 2) avg_marker_mu,
               ROUND(AVG(material_utilization), 2) avg_material_mu,
               ROUND(SUM(cutting_wastage_yds), 2) cutting_wastage_yds,
               ROUND(SUM(leftover_fabric), 2) leftover_yds
        FROM bulk_order WHERE {bulk_where}
        """,
        bulk_values,
    ).fetchone()
    chain_yy = conn.execute(
        f"""
        SELECT COUNT(*) sample_count,
               ROUND(AVG(quo_yy), 4) quo_yy,
               ROUND(AVG(ppo_yy), 4) ppo_yy,
               ROUND(AVG(bulk_yy), 4) bulk_yy,
               ROUND(AVG(yy_variance_quo_ppo), 4) quo_minus_ppo,
               ROUND(AVG(yy_variance_ppo_bulk), 4) ppo_minus_bulk,
               ROUND(AVG(yy_variance_quo_bulk), 4) quo_minus_bulk,
               ROUND(SUM(estimated_saved_yds), 2) estimated_saved_yds
        FROM chain_detail
        WHERE chain_state='full_chain'
          AND garment_order IN (SELECT garment_order FROM bulk_order WHERE {bulk_where})
        """,
        bulk_values,
    ).fetchone()
    conn.close()
    return {
        "customers": customer_rows[:30],
        "durations": duration,
        "rankings": entity_rankings,
        "timeouts": timeout_rows,
        "yy_stage": yy_stage,
        "bulk_yy": dict(bulk_yy),
        "chain_yy": dict(chain_yy),
        "definitions": {
            "deal_rate": "PPO Workflow 数 / QUO Workflow 数",
            "rebuy_rate": "重复 Bulk 订单数 / Bulk 订单数",
            "yy_delta": "PPO YY - Bulk YY，正数表示估算节省，负数表示超耗",
            "timeout_hours": timeout_hours,
        },
    }


def analytics_v2(params: dict[str, list[str]]) -> dict:
    conn = db()
    bulk_where, bulk_values = filtered_bulk(conn, params)
    workflow_where, workflow_values = filtered_workflow(conn, params)
    buyer_expr = "CASE WHEN instr(TRIM(buyer), ' (') > 0 THEN substr(TRIM(buyer), 1, instr(TRIM(buyer), ' (') - 1) ELSE TRIM(buyer) END"
    customer_expr = "CASE WHEN instr(TRIM(customer_name), ' (') > 0 THEN substr(TRIM(customer_name), 1, instr(TRIM(customer_name), ' (') - 1) ELSE TRIM(customer_name) END"

    customer_bulk = rows_to_dict(
        conn.execute(
            f"""
            SELECT {buyer_expr} name,
                   COUNT(DISTINCT garment_order) order_count,
                   COALESCE(SUM(CASE WHEN {valid_bulk_number('order_quantity')} THEN order_quantity ELSE 0 END), 0) order_pieces,
                   COALESCE(SUM(CASE WHEN {valid_bulk_number('cut_quantity')} THEN cut_quantity ELSE 0 END), 0) cut_pieces,
                   COALESCE(SUM(CASE WHEN {valid_bulk_number('cutting_wastage_yds')} THEN cutting_wastage_yds ELSE 0 END), 0) wastage_yds,
                   COALESCE(SUM(CASE WHEN {valid_bulk_number('leftover_fabric')} THEN leftover_fabric ELSE 0 END), 0) leftover_yds
            FROM bulk_order
            WHERE {bulk_where} AND buyer IS NOT NULL AND TRIM(buyer) <> ''
            GROUP BY {buyer_expr}
            """,
            bulk_values,
        ).fetchall()
    )
    customer_workflow = rows_to_dict(
        conn.execute(
            f"""
            SELECT {customer_expr} name,
                   COUNT(DISTINCT CASE WHEN stage='QUO' THEN workflow_no END) quo_count,
                   COUNT(DISTINCT CASE WHEN stage='PPO' THEN workflow_no END) ppo_count
            FROM workflow_order
            WHERE {workflow_where} AND customer_name IS NOT NULL AND TRIM(customer_name) <> ''
            GROUP BY {customer_expr}
            """,
            workflow_values,
        ).fetchall()
    )
    customer_quo_bulk = rows_to_dict(
        conn.execute(
            f"""
            SELECT {customer_expr} name,
                   COUNT(DISTINCT workflow_no) quo_to_bulk_count
            FROM workflow_order
            WHERE {workflow_where}
              AND stage='QUO'
              AND workflow_no IN (
                SELECT cd.quo_workflow_no
                FROM chain_detail cd
                WHERE cd.quo_workflow_no IS NOT NULL
                  AND cd.garment_order IN (
                    SELECT garment_order FROM bulk_order WHERE {bulk_where}
                  )
              )
            GROUP BY {customer_expr}
            """,
            [*workflow_values, *bulk_values],
        ).fetchall()
    )
    customer_month_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT {buyer_expr} name,
                   substr(delivery_date, 1, 7) month_key
            FROM bulk_order
            WHERE {bulk_where}
              AND delivery_date IS NOT NULL
              AND delivery_date_status='valid'
            GROUP BY {buyer_expr}, substr(delivery_date, 1, 7)
            """,
            bulk_values,
        ).fetchall()
    )
    customer_chain = rows_to_dict(
        conn.execute(
            f"""
            SELECT {buyer_expr} name,
                   AVG(yy_variance_ppo_bulk) yy_delta,
                   SUM(CASE WHEN {valid_bulk_number('estimated_saved_yds')} THEN estimated_saved_yds ELSE 0 END) estimated_saved_yds,
                   COUNT(*) valid_yy_sample_count
            FROM chain_detail
            WHERE chain_state='full_chain'
              AND garment_order IN (SELECT garment_order FROM bulk_order WHERE {bulk_where})
              AND {valid_workflow_yy('ppo_yy')}
              AND {valid_workflow_yy('quo_yy')}
              AND {valid_bulk_yy('bulk_yy')}
            GROUP BY {buyer_expr}
            """,
            bulk_values,
        ).fetchall()
    )
    workflow_map = {row["name"]: row for row in customer_workflow}
    quo_bulk_map = {row["name"]: row for row in customer_quo_bulk}
    chain_map = {row["name"]: row for row in customer_chain}
    month_map: dict[str, set[str]] = {}
    observed_months = {row["month_key"] for row in customer_month_rows if row["month_key"]}
    latest_month = max(observed_months) if observed_months else ""
    for row in customer_month_rows:
        if row["month_key"]:
            month_map.setdefault(row["name"], set()).add(row["month_key"])
    rebuy_map = {}
    for name, months in month_map.items():
        eligible_months = {month for month in months if month < latest_month}
        retained_months = {month for month in eligible_months if next_month_key(month) in months}
        rebuy_map[name] = round(len(retained_months) / len(eligible_months) * 100, 2) if eligible_months else None
    bulk_map = {row["name"]: row for row in customer_bulk}
    customers = []
    for name in sorted(set(bulk_map) | set(workflow_map)):
        row = {
            "name": name,
            "order_count": 0,
            "order_pieces": 0,
            "cut_pieces": 0,
            "wastage_yds": 0,
            "leftover_yds": 0,
            **bulk_map.get(name, {}),
        }
        wf = workflow_map.get(row["name"], {})
        quo_bulk = quo_bulk_map.get(row["name"], {})
        ch = chain_map.get(row["name"], {})
        order_count = int(row["order_count"] or 0)
        quo_count = int(wf.get("quo_count") or 0)
        ppo_count = int(wf.get("ppo_count") or 0)
        quo_to_bulk_count = int(quo_bulk.get("quo_to_bulk_count") or 0)
        customers.append(
            {
                **row,
                "deal_rate": round(quo_to_bulk_count / quo_count * 100, 2) if quo_count else None,
                "rebuy_rate": rebuy_map.get(row["name"]),
                "quo_count": quo_count,
                "ppo_count": ppo_count,
                "quo_to_bulk_count": quo_to_bulk_count,
                "yy_delta": ch.get("yy_delta"),
                "estimated_saved_yds": ch.get("estimated_saved_yds"),
                "valid_yy_sample_count": ch.get("valid_yy_sample_count", 0),
            }
        )
    customers.sort(key=lambda item: item["order_count"], reverse=True)

    duration = {
        "quo": duration_stats(conn, params, "QUO"),
        "ppo": duration_stats(conn, params, "PPO"),
    }
    entity_rankings = {}
    for key, column in [("factory", "factory_cd"), ("creator_dept", "creator_dept"), ("creator", "creator")]:
        entity_rankings[key] = rows_to_dict(
            conn.execute(
                f"""
                SELECT TRIM({column}) name,
                       COUNT(DISTINCT workflow_no) workflow_count,
                       ROUND(AVG(CASE WHEN duration_hours BETWEEN 0 AND 720 THEN duration_hours END), 2) avg_duration_hours,
                       ROUND(AVG(CASE WHEN {valid_workflow_yy('final_yy')} THEN final_yy END), 4) avg_yy
                FROM workflow_order
                WHERE {workflow_where} AND {column} IS NOT NULL AND TRIM({column}) <> ''
                GROUP BY TRIM({column})
                ORDER BY workflow_count DESC
                LIMIT 15
                """,
                workflow_values,
            ).fetchall()
        )

    timeout_hours = float(qvalue(params, "timeout_hours") or "48")
    timeout_rows = rows_to_dict(
        conn.execute(
            f"""
            SELECT workflow_no, stage, customer_name, factory_cd, creator, creator_dept,
                   style_no, submitted_at, completed_at, ROUND(duration_hours, 2) duration_hours
            FROM workflow_order
            WHERE {workflow_where}
              AND duration_hours > ? AND duration_hours <= 720
            ORDER BY duration_hours DESC
            LIMIT 10
            """,
            [*workflow_values, timeout_hours],
        ).fetchall()
    )

    yy_stage = rows_to_dict(
        conn.execute(
            f"""
            SELECT stage, COUNT(DISTINCT workflow_no) sample_count,
                   ROUND(AVG(final_yy), 4) avg_yy,
                   ROUND(AVG(marker_yy), 4) avg_marker_yy,
                   ROUND(AVG(marker_mu), 2) avg_marker_mu,
                   ROUND(AVG(weighted_mu), 2) avg_weighted_mu
            FROM workflow_order
            WHERE {workflow_where} AND {valid_workflow_yy('final_yy')}
            GROUP BY stage
            """,
            workflow_values,
        ).fetchall()
    )
    bulk_yy = dict(
        conn.execute(
            f"""
            SELECT
              SUM(CASE WHEN {valid_bulk_yy('bulk_marker_yy')} THEN 1 ELSE 0 END) sample_count,
              ROUND(AVG(CASE WHEN {valid_bulk_yy('bulk_marker_yy')} THEN bulk_marker_yy END), 4) avg_yy,
              ROUND(AVG(CASE WHEN material_utilization BETWEEN 0 AND 100 THEN material_utilization END), 2) avg_material_mu,
              ROUND(SUM(CASE WHEN {valid_bulk_number('cutting_wastage_yds')} THEN cutting_wastage_yds ELSE 0 END), 2) cutting_wastage_yds,
              ROUND(SUM(CASE WHEN {valid_bulk_number('leftover_fabric')} THEN leftover_fabric ELSE 0 END), 2) leftover_yds,
              SUM(CASE WHEN {valid_bulk_number('order_quantity')} THEN 1 ELSE 0 END) valid_order_quantity_count,
              SUM(CASE WHEN {valid_bulk_number('cut_quantity')} THEN 1 ELSE 0 END) valid_cut_quantity_count
            FROM bulk_order
            WHERE {bulk_where}
            """,
            bulk_values,
        ).fetchone()
    )
    chain_yy = dict(
        conn.execute(
            f"""
            SELECT COUNT(*) sample_count,
                   ROUND(AVG(quo_yy), 4) quo_yy,
                   ROUND(AVG(ppo_yy), 4) ppo_yy,
                   ROUND(AVG(bulk_yy), 4) bulk_yy,
                   ROUND(AVG(yy_variance_quo_ppo), 4) quo_minus_ppo,
                   ROUND(AVG(yy_variance_ppo_bulk), 4) ppo_minus_bulk,
                   ROUND(AVG(yy_variance_quo_bulk), 4) quo_minus_bulk,
                   ROUND(AVG(weighted_yy_reduction), 4) weighted_yy_reduction,
                   ROUND(SUM(CASE WHEN {valid_bulk_number('estimated_saved_yds')} THEN estimated_saved_yds ELSE 0 END), 2) estimated_saved_yds
            FROM chain_detail
            WHERE chain_state='full_chain'
              AND garment_order IN (SELECT garment_order FROM bulk_order WHERE {bulk_where})
              AND {valid_workflow_yy('quo_yy')}
              AND {valid_workflow_yy('ppo_yy')}
              AND {valid_bulk_yy('bulk_yy')}
            """,
            bulk_values,
        ).fetchone()
    )
    volume = rows_to_dict(
        conn.execute(
            f"""
            SELECT stage,
                   COUNT(DISTINCT workflow_no) order_count,
                   SUM(CASE WHEN submitted_at IS NOT NULL THEN 1 ELSE 0 END) submitted_count,
                   SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) completed_count
            FROM workflow_order
            WHERE {workflow_where}
            GROUP BY stage
            ORDER BY stage
            """,
            workflow_values,
        ).fetchall()
    )
    bulk_volume = dict(
        conn.execute(
            f"""
            SELECT COUNT(*) order_count,
                   SUM(CASE WHEN delivery_date_status='valid' THEN 1 ELSE 0 END) valid_delivery_count,
                   SUM(CASE WHEN delivery_date_status='valid' THEN 0 ELSE 1 END) invalid_delivery_count
            FROM bulk_order WHERE {bulk_where}
            """,
            bulk_values,
        ).fetchone()
    )
    quality = rows_to_dict(
        conn.execute(
            "SELECT issue_type, severity, COUNT(*) count FROM data_quality GROUP BY issue_type, severity ORDER BY count DESC"
        ).fetchall()
    )
    conn.close()
    return {
        "customers": customers[:50],
        "customer_rankings": {
            "order_count": sorted(customers, key=lambda item: item["order_count"], reverse=True)[:10],
            "order_pieces": sorted(customers, key=lambda item: float(item["order_pieces"] or 0), reverse=True)[:10],
            "deal_rate": sorted([item for item in customers if item["deal_rate"] is not None], key=lambda item: item["deal_rate"], reverse=True)[:10],
            "rebuy_rate": sorted(customers, key=lambda item: item["rebuy_rate"] if item["rebuy_rate"] is not None else -1, reverse=True)[:10],
            "yy_delta": sorted([item for item in customers if item["yy_delta"] is not None], key=lambda item: item["yy_delta"], reverse=True)[:10],
            "wastage_yds": sorted(customers, key=lambda item: float(item["wastage_yds"] or 0), reverse=True)[:10],
        },
        "durations": duration,
        "rankings": entity_rankings,
        "timeouts": timeout_rows,
        "yy_stage": yy_stage,
        "bulk_yy": bulk_yy,
        "chain_yy": chain_yy,
        "volume": {"workflow": volume, "bulk": bulk_volume},
        "quality": quality,
        "definitions": {
            "deal_rate": "可连接到 Bulk 的 QUO WorkflowNo 数 / 有效 QUO WorkflowNo 数 × 100%；不要求链路达到 Full chain，按客户名称归一化后计算",
            "rebuy_rate": "客户有 Bulk 订单的月份中，下一自然月仍有 Bulk 订单的月份 / 可观察到下一月份的有效月份 × 100%；数据集最后一个观察月不计入分母",
            "yy_saving_overuse": "PPO Marker YY - Bulk Marker YY；结果大于 0 表示估算节省，小于 0 表示超耗；只使用 Full chain 且三阶段 YY 有效的链路明细",
            "wastage_yds": "Bulk 订单聚合后的 Cutting Wastage (Yds) 非负值之和；空白和负数进入数据质量，不进入损耗码数",
            "avg_duration": "(Completed_DateTime - Published/Submited_DateTime) 换算为小时后取算术平均；仅保留 0 至 720 小时",
            "median_p90": "中位数为有效完成时长排序后的 50% 分位数，P90 为 90% 分位数，采用线性插值计算",
            "valid_yy_range": "0 < YY <= 20",
            "valid_duration_range": "0 <= 完成时长 <= 720 小时",
        },
    }


def filters() -> dict:
    conn = db()
    result = {}
    for key, table, column in [
        ("buyers", "bulk_order", "buyer"),
        ("fabric_sources", "bulk_order", "fabric_source"),
        ("chain_states", "bulk_order", "chain_state"),
        ("garment_features", "bulk_detail", "garment_feature"),
        ("factories", "workflow_order", "factory_cd"),
        ("styles", "workflow_order", "style_no"),
        ("creators", "workflow_order", "creator"),
        ("creator_depts", "workflow_order", "creator_dept"),
    ]:
        result[key] = [
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND TRIM({column}) <> '' ORDER BY {column} LIMIT 500"
            ).fetchall()
        ]
    result["meta"] = {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM app_meta")}
    conn.close()
    return result


def orders(params: dict[str, list[str]]) -> dict:
    conn = db()
    where, values = filtered_bulk(conn, params)
    search = qvalue(params, "search")
    if search:
        where += " AND (garment_order LIKE ? OR buyer LIKE ? OR ppo_workflow_no LIKE ? OR quo_workflow_no LIKE ?)"
        values.extend([f"%{search}%"] * 4)
    try:
        page = max(1, int(qvalue(params, "page") or "1"))
    except ValueError:
        page = 1
    try:
        page_size = min(100, max(10, int(qvalue(params, "page_size") or "25")))
    except ValueError:
        page_size = 25
    total = conn.execute(f"SELECT COUNT(*) FROM bulk_order WHERE {where}", values).fetchone()[0]
    data = rows_to_dict(
        conn.execute(
            f"""
            SELECT bo.garment_order, bo.buyer, bo.delivery_date, bo.delivery_date_status, bo.fabric_source,
                   bo.is_outside, bo.ppo_workflow_no, bo.quo_workflow_no, bo.chain_state,
                   bo.order_quantity, bo.cut_quantity, bo.analysis_scope,
                   yy.quo_marker_yy, yy.ppo_marker_yy, yy.bulk_marker_yy,
                   yy.quo_minus_ppo_marker_yy, yy.ppo_minus_bulk_marker_yy, yy.quo_minus_bulk_marker_yy
            FROM (
                SELECT * FROM bulk_order WHERE {where}
            ) bo
            LEFT JOIN (
                SELECT garment_order,
                       AVG(CASE WHEN quo_marker_yy > 0 AND quo_marker_yy <= 20 THEN quo_marker_yy END) quo_marker_yy,
                       AVG(CASE WHEN ppo_marker_yy_workflow > 0 AND ppo_marker_yy_workflow <= 20 THEN ppo_marker_yy_workflow END) ppo_marker_yy,
                       AVG(CASE WHEN bulk_marker_yy > 0 AND bulk_marker_yy <= 20 THEN bulk_marker_yy END) bulk_marker_yy,
                       AVG(CASE WHEN quo_marker_yy > 0 AND quo_marker_yy <= 20 AND ppo_marker_yy_workflow > 0 AND ppo_marker_yy_workflow <= 20 THEN quo_marker_yy - ppo_marker_yy_workflow END) quo_minus_ppo_marker_yy,
                       AVG(CASE WHEN ppo_marker_yy_workflow > 0 AND ppo_marker_yy_workflow <= 20 AND bulk_marker_yy > 0 AND bulk_marker_yy <= 20 THEN ppo_marker_yy_workflow - bulk_marker_yy END) ppo_minus_bulk_marker_yy,
                       AVG(CASE WHEN quo_marker_yy > 0 AND quo_marker_yy <= 20 AND bulk_marker_yy > 0 AND bulk_marker_yy <= 20 THEN quo_marker_yy - bulk_marker_yy END) quo_minus_bulk_marker_yy
                FROM chain_detail
                GROUP BY garment_order
            ) yy ON yy.garment_order = bo.garment_order
            ORDER BY bo.delivery_date DESC, bo.garment_order
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
    )
    conn.close()
    return {"page": page, "page_size": page_size, "total": total, "items": data}


def chain_detail(params: dict[str, list[str]]) -> dict:
    go = qvalue(params, "garment_order")
    conn = db()
    bulk = conn.execute("SELECT * FROM bulk_order WHERE garment_order = ?", (go,)).fetchone()
    details = rows_to_dict(
        conn.execute(
            "SELECT * FROM chain_detail WHERE garment_order = ? ORDER BY ppo_workflow_no", (go,)
        ).fetchall()
    )
    conn.close()
    return {"bulk": dict(bulk) if bulk else None, "details": details}


def data_quality(params: dict[str, list[str]]) -> dict:
    conn = db()
    bulk_where, bulk_values = filtered_bulk(conn, params)
    rows = rows_to_dict(
        conn.execute(
            "SELECT issue_type, severity, COUNT(*) count FROM data_quality GROUP BY issue_type, severity ORDER BY count DESC"
        ).fetchall()
    )
    recent = rows_to_dict(
        conn.execute(
            "SELECT entity_type, entity_id, issue_type, severity, field_name, raw_value, description, suggestion FROM data_quality ORDER BY id DESC LIMIT 100"
        ).fetchall()
    )
    states = rows_to_dict(
        conn.execute(
            f"SELECT COALESCE(chain_state, 'unknown') state, COUNT(*) count FROM bulk_order WHERE {bulk_where} GROUP BY chain_state ORDER BY count DESC",
            bulk_values,
        ).fetchall()
    )
    conn.close()
    return {"scope": "full_batch", "summary": rows, "items": recent, "states": states}


class Handler(BaseHTTPRequestHandler):
    def _send(
        self,
        payload: object,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, status: int = 302) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("无效的请求体")
        if length > 1_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def _user(self) -> dict | None:
        return admin_auth.user_from_headers(self.headers)

    def _require(
        self,
        permission: str | None = None,
        super_admin: bool = False,
    ) -> dict | None:
        user = self._user()
        if user is None:
            self._send({"error": "请先登录"}, 401)
            return None
        if super_admin and not admin_auth.user_is_super_admin(user):
            self._send({"error": "没有管理权限"}, 403)
            return None
        if permission and not admin_auth.user_has_permission(user, permission):
            self._send({"error": "没有页面权限"}, 403)
            return None
        return user

    def _admin_payload(self, user: dict) -> dict:
        return {
            "user": user,
            "permissions": [
                {"code": code, "name": name}
                for code, name in admin_auth.PERMISSIONS.items()
            ],
        }

    def _handle_auth_get(self, path: str) -> bool:
        if path != "/api/auth/me":
            return False
        user = self._require()
        if user is not None:
            self._send(self._admin_payload(user))
        return True

    def _handle_admin_get(self, path: str) -> bool:
        if path not in {"/api/admin/users", "/api/admin/roles"}:
            return False
        user = self._require("admin")
        if user is None:
            return True
        if path.endswith("/users"):
            self._send({"users": admin_auth.list_users(), "current_user": user})
        else:
            self._send({"roles": admin_auth.list_roles(), "current_user": user})
        return True

    def _handle_auth_post(self, path: str) -> bool:
        if path == "/api/auth/login":
            payload = self._body()
            user = admin_auth.authenticate(
                str(payload.get("username", "")),
                str(payload.get("password", "")),
            )
            if user is None:
                self._send({"error": "用户名或密码错误"}, 401)
                return True
            token = admin_auth.create_session(user["id"])
            self._send(
                {"user": user},
                headers={
                    "Set-Cookie": (
                        f"{admin_auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                        f"SameSite=Lax; Max-Age={admin_auth.SESSION_HOURS * 3600}"
                    )
                },
            )
            return True
        if path == "/api/auth/logout":
            admin_auth.delete_session(admin_auth.session_token(self.headers))
            self._send(
                {"ok": True},
                headers={
                    "Set-Cookie": (
                        f"{admin_auth.SESSION_COOKIE}=; Path=/; HttpOnly; "
                        "SameSite=Lax; Max-Age=0"
                    )
                },
            )
            return True
        return False

    def _handle_admin_post(self, path: str) -> bool:
        admin_paths = {
            "/api/admin/users/create",
            "/api/admin/users/update",
            "/api/admin/users/delete",
            "/api/admin/roles/create",
            "/api/admin/roles/update",
            "/api/admin/roles/delete",
        }
        if path not in admin_paths:
            return False
        user = self._require("admin", super_admin=True)
        if user is None:
            return True
        payload = self._body()
        if path == "/api/admin/users/create":
            result = admin_auth.create_user(
                payload.get("username", ""),
                payload.get("password", ""),
                payload.get("role_ids", []),
                bool(payload.get("active", True)),
            )
            self._send({"user": result})
        elif path == "/api/admin/users/update":
            result = admin_auth.update_user(
                int(payload["id"]),
                payload.get("role_ids", []),
                bool(payload.get("active", True)),
                payload.get("password") or None,
            )
            self._send({"user": result})
        elif path == "/api/admin/users/delete":
            admin_auth.delete_user(int(payload["id"]))
            self._send({"ok": True})
        elif path == "/api/admin/roles/create":
            result = admin_auth.create_role(
                payload.get("name", ""),
                payload.get("code", ""),
                payload.get("description", ""),
                payload.get("permissions", []),
                bool(payload.get("active", True)),
            )
            self._send({"role": result})
        elif path == "/api/admin/roles/update":
            result = admin_auth.update_role(
                int(payload["id"]),
                payload.get("name", ""),
                payload.get("code", ""),
                payload.get("description", ""),
                payload.get("permissions", []),
                bool(payload.get("active", True)),
            )
            self._send({"role": result})
        else:
            admin_auth.delete_role(int(payload["id"]))
            self._send({"ok": True})
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if self._handle_auth_get(parsed.path):
                return
            if self._handle_admin_get(parsed.path):
                return
            permission = PAGE_PERMISSIONS.get(parsed.path)
            if permission:
                if self._require(permission) is None:
                    return
            elif parsed.path == "/api/filters":
                user = self._require()
                if user is None or not any(
                    admin_auth.user_has_permission(user, item)
                    for item in BUSINESS_PERMISSIONS
                ):
                    if user is not None:
                        self._send({"error": "没有业务页面权限"}, 403)
                    return
            if parsed.path == "/api/summary":
                self._send(cached_response("summary", params, lambda: summary(params)))
            elif parsed.path == "/api/trend":
                self._send(cached_response("trend", params, lambda: trend(params)))
            elif parsed.path == "/api/rankings":
                self._send(cached_response("rankings", params, lambda: rankings(params)))
            elif parsed.path == "/api/analytics":
                self._send(cached_response("analytics", params, lambda: analytics_v2(params)))
            elif parsed.path == "/api/filters":
                self._send(cached_response("filters", {}, filters))
            elif parsed.path == "/api/orders":
                self._send(cached_response("orders", params, lambda: orders(params)))
            elif parsed.path == "/api/chain":
                self._send(cached_response("chain", params, lambda: chain_detail(params)))
            elif parsed.path == "/api/data-quality":
                self._send(cached_response("data-quality", params, lambda: data_quality(params)))
            else:
                requested = parsed.path.lstrip("/") or "index.html"
                user = self._user()
                if requested in {"", "index.html"}:
                    if user is None:
                        self._redirect("/login.html")
                    else:
                        self._file(FRONTEND / "index.html")
                elif requested == "admin.html":
                    if user is None:
                        self._redirect("/login.html")
                    elif not admin_auth.user_has_permission(user, "admin"):
                        self._redirect("/")
                    else:
                        self._file(FRONTEND / requested)
                else:
                    self._file(FRONTEND / requested)
        except ValueError as exc:
            self._send({"error": str(exc)}, 400)
        except Exception as exc:
            self._send({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if self._handle_auth_post(parsed.path):
                return
            if self._handle_admin_post(parsed.path):
                return
            self._send({"error": "Not Found"}, 404)
        except (KeyError, TypeError, ValueError) as exc:
            self._send({"error": str(exc) or "请求参数错误"}, 400)
        except Exception as exc:
            self._send({"error": str(exc)}, 500)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Missing database: {DB_PATH}. Run scripts/build_demo_db.py first.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"YY Fabric Dashboard listening on {HOST}:{PORT}")
    print(f"Local:   http://127.0.0.1:{PORT}")
    try:
        addresses = sorted(
            {
                address
                for address in socket.gethostbyname_ex(socket.gethostname())[2]
                if address and not address.startswith("127.")
            }
        )
    except OSError:
        addresses = []
    for address in addresses:
        print(f"LAN:     http://{address}:{PORT}")
    if not addresses:
        print(f"LAN:     find this computer's IPv4 address and open http://<IPv4>:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
