from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import xlrd


# Keep column order aligned with the AE Excel export.
EXCEL_COLUMNS = [
    "文件名称",
    "文件编号",
    "文件版本",
    "所属项目",
    "制造单位",
    "流程状态",
    "版本状态",
    "是否分章节",
    "创建时间",
    "发起人",
    "文件类别",
    "适用机组号",
    "供应商名称",
    "设备名称",
    "合同号",
    "核安全报送级别",
    "是否采购分包",
    "是否含SPV设备",
    "SPV位号",
    "总包方部门",
    "板块",
    "相关供方工作模式",
    "制造单位供方级别",
    "审查结论",
    "发起单位",
]
PRIMARY_KEY = "文件编号"
META_COLUMNS = ("fetched_at", "source_file", "updated_at")
# Business fields that are compared for change tracking; PK itself never changes identity.
TRACKED_COLUMNS = [name for name in EXCEL_COLUMNS if name != PRIMARY_KEY]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    column_defs = [f"{_quote(name)} TEXT" for name in EXCEL_COLUMNS]
    column_defs.append("fetched_at TEXT NOT NULL")
    column_defs.append("source_file TEXT")
    column_defs.append("updated_at TEXT NOT NULL")
    ddl = (
        "CREATE TABLE IF NOT EXISTS documents (\n  "
        + ",\n  ".join(column_defs)
        + f",\n  PRIMARY KEY ({_quote(PRIMARY_KEY)})\n)"
    )
    conn.execute(ddl)
    # Older DB files created before meta columns existed keep working.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    for name in META_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} TEXT")

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS document_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {_quote(PRIMARY_KEY)} TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            changed_at TEXT NOT NULL,
            source_file TEXT,
            sync_batch_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_document_changes_pk_time
        ON document_changes ({_quote(PRIMARY_KEY)}, changed_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_changes_batch
        ON document_changes (sync_batch_id)
        """
    )
    conn.commit()


def _cell_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip()


def read_excel_rows(excel_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    book = xlrd.open_workbook(str(excel_path))
    sheet = book.sheet_by_index(0)
    if sheet.nrows < 1:
        raise RuntimeError(f"Excel 没有表头: {excel_path}")
    headers = [_cell_to_text(sheet.cell_value(0, col)) for col in range(sheet.ncols)]
    if PRIMARY_KEY not in headers:
        raise RuntimeError(f"Excel 缺少主键列 {PRIMARY_KEY!r}，实际表头={headers}")
    missing = [name for name in EXCEL_COLUMNS if name not in headers]
    if missing:
        raise RuntimeError(f"Excel 缺少预期列: {missing}")

    index = {name: headers.index(name) for name in EXCEL_COLUMNS}
    rows: list[dict[str, str]] = []
    for row_idx in range(1, sheet.nrows):
        record = {
            name: _cell_to_text(sheet.cell_value(row_idx, index[name]))
            for name in EXCEL_COLUMNS
        }
        if not record[PRIMARY_KEY]:
            continue
        rows.append(record)
    return headers, rows


def _diff_fields(existing: sqlite3.Row, record: dict[str, str]) -> list[tuple[str, str, str]]:
    diffs: list[tuple[str, str, str]] = []
    for name in TRACKED_COLUMNS:
        old_value = str(existing[name] or "")
        new_value = record[name]
        if old_value != new_value:
            diffs.append((name, old_value, new_value))
    return diffs


def upsert_excel(db_path: Path, excel_path: Path) -> dict[str, int | str]:
    _, rows = read_excel_rows(excel_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = excel_path.name
    sync_batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    insert_cols = [*EXCEL_COLUMNS, "fetched_at", "source_file", "updated_at"]
    placeholders = ", ".join("?" for _ in insert_cols)
    update_assignments = [
        f"{_quote(name)}=excluded.{_quote(name)}"
        for name in EXCEL_COLUMNS
        if name != PRIMARY_KEY
    ]
    update_assignments.extend(
        [
            "fetched_at=excluded.fetched_at",
            "source_file=excluded.source_file",
            "updated_at=excluded.updated_at",
        ]
    )
    sql = (
        f"INSERT INTO documents ({', '.join(_quote(c) for c in insert_cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT({_quote(PRIMARY_KEY)}) DO UPDATE SET "
        + ", ".join(update_assignments)
    )
    change_sql = (
        f"INSERT INTO document_changes "
        f"({_quote(PRIMARY_KEY)}, field_name, old_value, new_value, changed_at, source_file, sync_batch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )

    inserted = 0
    updated = 0
    unchanged = 0
    changed_fields = 0
    with connect(db_path) as conn:
        ensure_schema(conn)
        for record in rows:
            pk = record[PRIMARY_KEY]
            existing = conn.execute(
                f"SELECT * FROM documents WHERE {_quote(PRIMARY_KEY)}=?",
                (pk,),
            ).fetchone()
            values = [record[name] for name in EXCEL_COLUMNS] + [now, source, now]
            if existing is None:
                conn.execute(sql, values)
                inserted += 1
                continue

            diffs = _diff_fields(existing, record)
            if not diffs:
                # Still refresh sync markers so operators can see the last successful pull.
                conn.execute(
                    f"UPDATE documents SET fetched_at=?, source_file=? WHERE {_quote(PRIMARY_KEY)}=?",
                    (now, source, pk),
                )
                unchanged += 1
                continue

            conn.execute(sql, values)
            conn.executemany(
                change_sql,
                [
                    (pk, field_name, old_value, new_value, now, source, sync_batch_id)
                    for field_name, old_value, new_value in diffs
                ],
            )
            updated += 1
            changed_fields += len(diffs)
        conn.commit()

    return {
        "total": len(rows),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "changed_fields": changed_fields,
        "sync_batch_id": sync_batch_id,
    }
