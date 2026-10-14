from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "dashboard.sqlite"


SCHEMA = """
DROP TABLE IF EXISTS workflow_order;
DROP TABLE IF EXISTS bulk_detail;
DROP TABLE IF EXISTS bulk_order;
DROP TABLE IF EXISTS chain_detail;
DROP TABLE IF EXISTS data_quality;
DROP TABLE IF EXISTS app_meta;

CREATE TABLE workflow_order (
    workflow_no TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    customer_name TEXT,
    factory_cd TEXT,
    style_no TEXT,
    creator TEXT,
    creator_dept TEXT,
    submitted_at TEXT,
    completed_at TEXT,
    duration_hours REAL,
    final_yy REAL,
    marker_yy REAL,
    marker_mu REAL,
    weighted_mu REAL
);

CREATE TABLE bulk_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    garment_order TEXT NOT NULL,
    factory_code TEXT,
    style_description TEXT,
    garment_feature TEXT
);

CREATE TABLE bulk_order (
    garment_order TEXT PRIMARY KEY,
    buyer TEXT,
    delivery_date TEXT,
    delivery_date_status TEXT,
    fabric_source TEXT,
    is_outside INTEGER,
    yy_job_no TEXT,
    ppo_workflow_no TEXT,
    quo_workflow_no TEXT,
    chain_state TEXT,
    analysis_scope TEXT,
    row_count INTEGER,
    fty_job_order_count INTEGER,
    order_quantity REAL,
    cut_quantity REAL,
    shipped_quantity REAL,
    warehouse_shipped_quantity REAL,
    ppo_order_yds REAL,
    issued REAL,
    marker_audited REAL,
    ship_yardage REAL,
    ppo_marker_yy REAL,
    bulk_marker_yy REAL,
    marker_yy_variance REAL,
    marker_utilization REAL,
    material_utilization REAL,
    cutting_wastage_yds REAL,
    cutting_wastage_rate REAL,
    sewing_wastage_pcs REAL,
    sewing_wastage_rate REAL,
    washing_wastage_pcs REAL,
    washing_wastage_rate REAL,
    printing_wastage_pcs REAL,
    printing_wastage_rate REAL,
    leftover_fabric REAL
);

CREATE TABLE chain_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    garment_order TEXT,
    ppo_workflow_no TEXT,
    quo_workflow_no TEXT,
    style_no TEXT,
    buyer TEXT,
    customer_name TEXT,
    factory_cd TEXT,
    creator TEXT,
    creator_dept TEXT,
    chain_state TEXT,
    match_method TEXT,
    ppo_submitted_at TEXT,
    ppo_completed_at TEXT,
    ppo_duration_hours REAL,
    quo_submitted_at TEXT,
    quo_completed_at TEXT,
    quo_duration_hours REAL,
    ppo_yy REAL,
    ppo_marker_yy_workflow REAL,
    quo_yy REAL,
    quo_marker_yy REAL,
    bulk_yy REAL,
    bulk_marker_yy REAL,
    yy_variance_ppo_bulk REAL,
    yy_variance_quo_ppo REAL,
    yy_variance_quo_bulk REAL,
    weighted_yy_reduction REAL,
    estimated_saved_yds REAL
);

CREATE TABLE data_quality (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT,
    entity_id TEXT,
    issue_type TEXT,
    severity TEXT,
    description TEXT,
    field_name TEXT,
    raw_value TEXT,
    suggestion TEXT
);

CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX idx_bulk_detail_go ON bulk_detail(garment_order);
CREATE INDEX idx_bulk_detail_factory ON bulk_detail(factory_code);
CREATE INDEX idx_bulk_order_chain ON bulk_order(chain_state);
CREATE INDEX idx_bulk_order_date ON bulk_order(delivery_date);
CREATE INDEX idx_chain_go ON chain_detail(garment_order);
CREATE INDEX idx_workflow_stage_date ON workflow_order(stage, submitted_at);
"""


def insert_row(conn: sqlite3.Connection, table: str, values: dict) -> None:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    selected = [values.get(column) for column in columns]
    placeholders = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        selected,
    )


def workflow_row(
    stage: str,
    workflow_no: str,
    customer: str,
    factory: str,
    style: str,
    creator: str,
    submitted: datetime,
    duration: float,
    yy: float,
) -> dict:
    completed = submitted + timedelta(hours=duration)
    return {
        "workflow_no": workflow_no,
        "stage": stage,
        "customer_name": customer,
        "factory_cd": factory,
        "style_no": style,
        "creator": creator,
        "creator_dept": "Demo Planning",
        "submitted_at": submitted.isoformat(sep=" "),
        "completed_at": completed.isoformat(sep=" "),
        "duration_hours": duration,
        "final_yy": yy,
        "marker_yy": yy - 0.04,
        "marker_mu": 91.5 + (yy % 1) * 2,
        "weighted_mu": 89.5 + (yy % 1) * 2,
    }


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    customers = ["Northwind Sports", "Evergreen Apparel", "Metro Outfitters"]
    factories = ["Demo Factory A", "Demo Factory B"]
    styles = ["DEMO-TEE", "DEMO-HOODIE", "DEMO-JACKET"]
    creators = ["Demo Alice", "Demo Bob", "Demo Chen"]
    base_date = datetime(2025, 1, 8, 9, 0)

    orders = [
        ("DEMO-GO-001", 0, "Northwind Sports", "full_chain"),
        ("DEMO-GO-002", 0, "Northwind Sports", "full_chain"),
        ("DEMO-GO-003", 0, "Northwind Sports", "full_chain"),
        ("DEMO-GO-004", 0, "Evergreen Apparel", "full_chain"),
        ("DEMO-GO-005", 0, "Evergreen Apparel", "full_chain"),
        ("DEMO-GO-006", 0, "Evergreen Apparel", "partial_chain"),
        ("DEMO-GO-007", 0, "Metro Outfitters", "full_chain"),
        ("DEMO-GO-008", 0, "Metro Outfitters", "ppo_only"),
        ("DEMO-GO-009", 0, "Metro Outfitters", "full_chain"),
        ("DEMO-GO-010", 0, "Northwind Sports", "full_chain"),
        ("DEMO-GO-011", 1, "Evergreen Apparel", "full_chain"),
        ("DEMO-GO-012", 1, "Metro Outfitters", "no_ppo"),
    ]

    for index, (garment_order, is_outside, buyer, state) in enumerate(orders, start=1):
        factory = factories[index % len(factories)]
        style = styles[index % len(styles)]
        creator = creators[index % len(creators)]
        ppo_no = f"DEMO-PPO-{index:03d}" if state in {"full_chain", "partial_chain", "ppo_only"} else None
        quo_no = f"DEMO-QUO-{index:03d}" if state == "full_chain" else None
        submitted = base_date + timedelta(days=index * 18)
        delivery = (submitted + timedelta(days=18)).date().isoformat()
        if garment_order == "DEMO-GO-010":
            delivery_status = "invalid_format"
            delivery = "unknown"
        elif garment_order == "DEMO-GO-012":
            delivery_status = "missing"
            delivery = None
        else:
            delivery_status = "valid"

        ppo_yy = round(2.05 + (index % 4) * 0.08, 4)
        bulk_yy = round(ppo_yy - 0.12 + (index % 3) * 0.04, 4)
        order_quantity = 420 + index * 35
        cut_quantity = order_quantity - 12
        variance = round(ppo_yy - bulk_yy, 4)
        insert_row(
            conn,
            "bulk_order",
            {
                "garment_order": garment_order,
                "buyer": buyer,
                "delivery_date": delivery,
                "delivery_date_status": delivery_status,
                "fabric_source": "Outside" if is_outside else "Internal",
                "is_outside": is_outside,
                "yy_job_no": ppo_no,
                "ppo_workflow_no": ppo_no,
                "quo_workflow_no": quo_no,
                "chain_state": state,
                "analysis_scope": "outside_no_ppo_removed" if state == "no_ppo" else "main",
                "row_count": 1,
                "fty_job_order_count": 1,
                "order_quantity": order_quantity,
                "cut_quantity": cut_quantity,
                "shipped_quantity": cut_quantity - 8,
                "warehouse_shipped_quantity": cut_quantity - 8,
                "ppo_order_yds": round(cut_quantity * ppo_yy, 2),
                "issued": round(cut_quantity * bulk_yy * 1.01, 2),
                "marker_audited": round(cut_quantity * bulk_yy, 2),
                "ship_yardage": round(cut_quantity * bulk_yy * 0.98, 2),
                "ppo_marker_yy": ppo_yy,
                "bulk_marker_yy": bulk_yy,
                "marker_yy_variance": variance,
                "marker_utilization": 88.0 + index % 7,
                "material_utilization": 84.0 + index % 8,
                "cutting_wastage_yds": round(7.5 + index * 0.4, 2),
                "cutting_wastage_rate": 1.8 + index % 4 * 0.2,
                "sewing_wastage_pcs": 2 + index % 5,
                "sewing_wastage_rate": 0.4 + index % 3 * 0.1,
                "washing_wastage_pcs": 1 + index % 3,
                "washing_wastage_rate": 0.2 + index % 2 * 0.1,
                "printing_wastage_pcs": index % 4,
                "printing_wastage_rate": 0.1 + index % 2 * 0.1,
                "leftover_fabric": round(4.0 + index * 0.25, 2),
            },
        )
        insert_row(
            conn,
            "bulk_detail",
            {
                "garment_order": garment_order,
                "factory_code": factory,
                "style_description": style,
                "garment_feature": "Demo Feature A" if index % 2 else "Demo Feature B",
            },
        )

        if ppo_no:
            ppo_submitted = submitted + timedelta(hours=5)
            ppo = workflow_row(
                "PPO",
                ppo_no,
                buyer,
                factory,
                style,
                creator,
                ppo_submitted,
                20 + index * 2,
                ppo_yy,
            )
            insert_row(conn, "workflow_order", ppo)
            if quo_no:
                quo = workflow_row(
                    "QUO",
                    quo_no,
                    buyer,
                    factory,
                    style,
                    creator,
                    submitted,
                    10 + index,
                    ppo_yy + 0.16,
                )
                insert_row(conn, "workflow_order", quo)
                quo_yy = quo["final_yy"]
            else:
                quo = None
                quo_yy = None

            insert_row(
                conn,
                "chain_detail",
                {
                    "garment_order": garment_order,
                    "ppo_workflow_no": ppo_no,
                    "quo_workflow_no": quo_no,
                    "style_no": style,
                    "buyer": buyer,
                    "customer_name": buyer,
                    "factory_cd": factory,
                    "creator": creator,
                    "creator_dept": "Demo Planning",
                    "chain_state": state,
                    "match_method": "synthetic_demo_match",
                    "ppo_submitted_at": ppo["submitted_at"],
                    "ppo_completed_at": ppo["completed_at"],
                    "ppo_duration_hours": ppo["duration_hours"],
                    "quo_submitted_at": quo["submitted_at"] if quo else None,
                    "quo_completed_at": quo["completed_at"] if quo else None,
                    "quo_duration_hours": quo["duration_hours"] if quo else None,
                    "ppo_yy": ppo_yy,
                    "ppo_marker_yy_workflow": ppo["marker_yy"],
                    "quo_yy": quo_yy,
                    "quo_marker_yy": quo["marker_yy"] if quo else None,
                    "bulk_yy": bulk_yy,
                    "bulk_marker_yy": bulk_yy,
                    "yy_variance_ppo_bulk": variance,
                    "yy_variance_quo_ppo": round(quo_yy - ppo_yy, 4) if quo_yy else None,
                    "yy_variance_quo_bulk": round(quo_yy - bulk_yy, 4) if quo_yy else None,
                    "weighted_yy_reduction": variance,
                    "estimated_saved_yds": round(variance * cut_quantity, 2),
                },
            )

    insert_row(
        conn,
        "workflow_order",
        workflow_row(
            "QUO",
            "DEMO-QUO-UNLINKED",
            customers[2],
            factories[0],
            styles[0],
            creators[0],
            datetime(2026, 2, 4, 9, 0),
            84,
            2.55,
        ),
    )

    quality_rows = [
        ("Bulk", "DEMO-GO-010", "invalid_delivery_date", "warning", "Delivery date is not parseable.", "Delivery Date", "unknown", "Correct the delivery date in the source system."),
        ("Bulk", "DEMO-GO-012", "missing_yy_job_no", "warning", "No PPO reference is available for this synthetic Outside order.", "YY Job No", "", "Maintain a valid PPO workflow number before analysis."),
        ("Workflow", "DEMO-QUO-UNLINKED", "missing_bulk_link", "info", "Quotation is not connected to a Bulk order.", "WorkflowNo", "DEMO-QUO-UNLINKED", "Confirm whether the quotation became a production order."),
    ]
    conn.executemany(
        """
        INSERT INTO data_quality(
            entity_type, entity_id, issue_type, severity, description,
            field_name, raw_value, suggestion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        quality_rows,
    )
    conn.executemany(
        "INSERT INTO app_meta(key, value) VALUES (?, ?)",
        [
            ("database_version", "public-synthetic-demo"),
            ("analysis_scope", "Synthetic data only; Outside without PPO is excluded from main scope."),
            ("workflow_submit_field", "Published/Submited_DateTime"),
            ("workflow_complete_field", "Completed_DateTime"),
            ("bulk_delivery_field", "Delivery Date"),
            ("bulk_yy_aggregation", "Cut Quantity weighted average"),
        ],
    )
    conn.commit()
    conn.close()
    print(f"Built synthetic database: {DB_PATH}")


if __name__ == "__main__":
    build()
