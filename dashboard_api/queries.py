from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .db import connect, qident, resolve_db_path


STATUS_COLORS = {
    "完成": "#27b99a",
    "审查/选点": "#f4ad48",
    "制造方编制": "#668ff0",
    "制造方审核": "#9c82ed",
    "其他": "#9aaabc",
}
COMPANY_COLORS = ["#29bfd0", "#668ff0", "#27b99a", "#f4ad48", "#9c82ed", "#5a88e4", "#e79b35", "#20ad89"]
REPORT_COLORS = ["#29bfd0", "#668ff0", "#f4ad48", "#9c82ed", "#9aaabc", "#27b99a"]

STATUS_SHORT = {
    "完成": "完成",
    "上海院监造人员审查/选点": "审查/选点",
    "制造方编制": "制造方编制",
    "制造方审核": "制造方审核",
}

STATUS_TONE = {
    "完成": "green",
    "审查/选点": "orange",
    "制造方编制": "blue",
    "制造方审核": "purple",
}


def short_status(raw: str) -> str:
    value = (raw or "").strip()
    return STATUS_SHORT.get(value, value or "未填写")


def short_company(name: str) -> str:
    text = (name or "").strip()
    for token in ("股份有限公司", "有限公司", "有限责任公司", "集团公司", "集团"):
        text = text.replace(token, "")
    return text[:10] or "未填写"


def status_tone(raw: str) -> str:
    return STATUS_TONE.get(short_status(raw), "blue")


def period_start(period: str) -> str | None:
    today = date.today()
    if period == "近30天":
        return (today - timedelta(days=30)).isoformat()
    if period == "本季度":
        quarter = (today.month - 1) // 3
        return date(today.year, quarter * 3 + 1, 1).isoformat()
    if period == "本年度":
        return date(today.year, 1, 1).isoformat()
    return None


def build_filters(project: str, group: str, period: str, status: str = "", q: str = "") -> tuple[str, list[Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if project and project != "全部":
        clauses.append(f"{qident('所属项目')}=?")
        params.append(project)
    if group and group != "全部":
        clauses.append(f"{qident('适用机组号')}=?")
        params.append(group)
    start = period_start(period)
    if start:
        clauses.append(f"{qident('创建时间')}>=?")
        params.append(start)
    if status and status != "全部":
        # Accept either short or full status labels.
        full_values = [k for k, v in STATUS_SHORT.items() if v == status]
        if full_values:
            placeholders = ", ".join("?" for _ in full_values)
            clauses.append(f"{qident('流程状态')} IN ({placeholders})")
            params.extend(full_values)
        else:
            clauses.append(f"{qident('流程状态')}=?")
            params.append(status)
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "("
            f"{qident('文件名称')} LIKE ? OR "
            f"{qident('文件编号')} LIKE ? OR "
            f"{qident('制造单位')} LIKE ?"
            ")"
        )
        params.extend([like, like, like])
    return " AND ".join(clauses), params


def fetch_distinct(conn, column: str) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT {qident(column)} AS v FROM documents "
        f"WHERE {qident(column)} IS NOT NULL AND TRIM({qident(column)})!='' "
        f"ORDER BY {qident(column)}"
    ).fetchall()
    return [str(row["v"]) for row in rows]


def group_count(conn, column: str, where: str, params: list[Any], limit: int | None = None) -> list[dict]:
    sql = (
        f"SELECT COALESCE(NULLIF(TRIM({qident(column)}), ''), '未填写') AS label, COUNT(*) AS value "
        f"FROM documents WHERE {where} "
        f"GROUP BY 1 ORDER BY value DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [{"label": row["label"], "value": int(row["value"])} for row in conn.execute(sql, params)]


def meta(conn) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*) AS total, MAX(fetched_at) AS last_fetched, "
        f"MIN({qident('创建时间')}) AS min_created, MAX({qident('创建时间')}) AS max_created "
        f"FROM documents"
    ).fetchone()
    change_count = conn.execute("SELECT COUNT(*) FROM document_changes").fetchone()[0]
    return {
        "dbPath": str(resolve_db_path()),
        "totalDocuments": int(row["total"] or 0),
        "lastFetchedAt": row["last_fetched"],
        "createdRange": [row["min_created"], row["max_created"]],
        "changeCount": int(change_count or 0),
    }


def get_filter_options() -> dict:
    with connect() as conn:
        return {
            "projects": ["全部", *fetch_distinct(conn, "所属项目")],
            "groups": ["全部", *fetch_distinct(conn, "适用机组号")],
            "periods": ["全部", "近30天", "本季度", "本年度"],
            "statuses": ["全部", "完成", "审查/选点", "制造方编制", "制造方审核"],
            "meta": meta(conn),
        }


def get_overview(project: str, group: str, period: str) -> dict:
    where, params = build_filters(project, group, period)
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", params).fetchone()[0]
        status_rows = group_count(conn, "流程状态", where, params)
        company_rows = group_count(conn, "制造单位", where, params)
        report_rows = group_count(conn, "核安全报送级别", where, params)
        unit_rows = group_count(conn, "适用机组号", where, params)

        status_stats = []
        for row in status_rows:
            label = short_status(row["label"])
            existing = next((item for item in status_stats if item["label"] == label), None)
            if existing:
                existing["value"] += row["value"]
            else:
                status_stats.append(
                    {
                        "label": label,
                        "value": row["value"],
                        "color": STATUS_COLORS.get(label, STATUS_COLORS["其他"]),
                    }
                )

        completed = next((item["value"] for item in status_stats if item["label"] == "完成"), 0)
        in_progress = total - completed
        review = next((item["value"] for item in status_stats if item["label"] == "审查/选点"), 0)
        drafting = next((item["value"] for item in status_stats if item["label"] == "制造方编制"), 0)
        auditing = next((item["value"] for item in status_stats if item["label"] == "制造方审核"), 0)
        company_count = len(company_rows)
        top_companies = [
            {
                "label": short_company(item["label"]),
                "fullLabel": item["label"],
                "value": item["value"],
                "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
            }
            for index, item in enumerate(company_rows[:5])
        ]
        others = sum(item["value"] for item in company_rows[5:])
        reporting_stats = [
            {
                "label": item["label"],
                "value": item["value"],
                "color": REPORT_COLORS[index % len(REPORT_COLORS)],
            }
            for index, item in enumerate(report_rows)
        ]
        filled_report = sum(item["value"] for item in report_rows if item["label"] != "未填写")
        top_company_note = (
            f"{top_companies[0]['label']} {top_companies[0]['value']} 份"
            if top_companies
            else "暂无制造单位"
        )

        latest = conn.execute(
            f"""
            SELECT {qident('文件名称')} AS name,
                   {qident('文件编号')} AS code,
                   {qident('制造单位')} AS company,
                   {qident('流程状态')} AS status,
                   {qident('创建时间')} AS date
            FROM documents
            WHERE {where}
            ORDER BY {qident('创建时间')} DESC, {qident('文件编号')} DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
        plans = [
            {
                "name": row["name"],
                "code": row["code"],
                "company": row["company"],
                "status": short_status(row["status"]),
                "tone": status_tone(row["status"]),
                "date": row["date"] or "",
            }
            for row in latest
        ]

        completion_rate = round(completed * 100 / total, 1) if total else 0.0
        in_progress_rate = round(in_progress * 100 / total, 1) if total else 0.0
        report_rate = round(filled_report * 100 / total, 1) if total else 0.0

        return {
            "meta": meta(conn),
            "metrics": [
                {
                    "label": "质量计划总数",
                    "value": str(total),
                    "unit": "份质量计划",
                    "note": f"覆盖 {len(unit_rows)} 个机组号",
                    "icon": "document",
                    "tone": "cyan",
                },
                {
                    "label": "流程已完成",
                    "value": str(completed),
                    "unit": "份",
                    "note": f"完成率 {completion_rate}%",
                    "icon": "check",
                    "tone": "green",
                    "progress": completion_rate,
                },
                {
                    "label": "流程处理中",
                    "value": str(in_progress),
                    "unit": "份",
                    "note": f"{review} 审查/选点 · {drafting + auditing} 编制/审核",
                    "icon": "clock",
                    "tone": "orange",
                    "progress": in_progress_rate,
                },
                {
                    "label": "制造单位",
                    "value": str(company_count),
                    "unit": "家",
                    "note": top_company_note,
                    "icon": "building",
                    "tone": "blue",
                },
            ],
            "statusStats": status_stats,
            "companyStats": top_companies,
            "companyFootnote": f"其余 {max(company_count - 5, 0)} 家制造单位共 {others} 份",
            "reportingStats": reporting_stats,
            "reportingFilled": filled_report,
            "reportingRate": report_rate,
            "plans": plans,
            "unitStats": [
                {"label": item["label"], "value": item["value"], "color": COMPANY_COLORS[i % len(COMPANY_COLORS)]}
                for i, item in enumerate(unit_rows)
            ],
        }


def get_documents(
    project: str,
    group: str,
    period: str,
    status: str,
    q: str,
    page: int,
    page_size: int,
) -> dict:
    where, params = build_filters(project, group, period, status, q)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    offset = (page - 1) * page_size
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
              {qident('文件名称')} AS name,
              {qident('文件编号')} AS code,
              {qident('文件版本')} AS version,
              {qident('所属项目')} AS project,
              {qident('制造单位')} AS company,
              {qident('流程状态')} AS status,
              {qident('版本状态')} AS versionStatus,
              {qident('创建时间')} AS createdAt,
              {qident('发起人')} AS initiator,
              {qident('文件类别')} AS category,
              {qident('适用机组号')} AS unit,
              {qident('核安全报送级别')} AS reportLevel,
              {qident('相关供方工作模式')} AS workMode,
              {qident('合同号')} AS contractNo,
              fetched_at AS fetchedAt,
              updated_at AS updatedAt
            FROM documents
            WHERE {where}
            ORDER BY {qident('创建时间')} DESC, {qident('文件编号')} DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["statusShort"] = short_status(item["status"])
            item["tone"] = status_tone(item["status"])
            items.append(item)
        return {
            "total": int(total),
            "page": page,
            "pageSize": page_size,
            "items": items,
        }


def get_trace(project: str, group: str, period: str) -> dict:
    where, params = build_filters(project, group, period)
    with connect() as conn:
        status_rows = group_count(conn, "流程状态", where, params)
        pipeline = []
        for raw in ["制造方编制", "制造方审核", "上海院监造人员审查/选点", "完成"]:
            count = next((item["value"] for item in status_rows if item["label"] == raw), 0)
            label = short_status(raw)
            pipeline.append(
                {
                    "label": label,
                    "value": count,
                    "tone": status_tone(raw),
                    "color": STATUS_COLORS.get(label, STATUS_COLORS["其他"]),
                }
            )
        in_progress = conn.execute(
            f"""
            SELECT
              {qident('文件名称')} AS name,
              {qident('文件编号')} AS code,
              {qident('制造单位')} AS company,
              {qident('流程状态')} AS status,
              {qident('创建时间')} AS date,
              {qident('发起人')} AS initiator
            FROM documents
            WHERE {where} AND {qident('流程状态')} != '完成'
            ORDER BY {qident('创建时间')} DESC
            LIMIT 30
            """,
            params,
        ).fetchall()
        changes = conn.execute(
            f"""
            SELECT
              c.{qident('文件编号')} AS code,
              d.{qident('文件名称')} AS name,
              c.field_name AS fieldName,
              c.old_value AS oldValue,
              c.new_value AS newValue,
              c.changed_at AS changedAt,
              c.sync_batch_id AS syncBatchId
            FROM document_changes c
            LEFT JOIN documents d ON d.{qident('文件编号')} = c.{qident('文件编号')}
            ORDER BY c.id DESC
            LIMIT 50
            """
        ).fetchall()
        return {
            "pipeline": pipeline,
            "inProgress": [
                {
                    **dict(row),
                    "statusShort": short_status(row["status"]),
                    "tone": status_tone(row["status"]),
                }
                for row in in_progress
            ],
            "recentChanges": [dict(row) for row in changes],
        }


def get_suppliers(project: str, group: str, period: str) -> dict:
    where, params = build_filters(project, group, period)
    with connect() as conn:
        companies = group_count(conn, "制造单位", where, params)
        modes = group_count(conn, "相关供方工作模式", where, params)
        levels = group_count(conn, "制造单位供方级别", where, params)
        ranking = [
            {
                "rank": index + 1,
                "label": short_company(item["label"]),
                "fullLabel": item["label"],
                "value": item["value"],
                "share": 0.0,
                "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
            }
            for index, item in enumerate(companies)
        ]
        total = sum(item["value"] for item in ranking) or 1
        for item in ranking:
            item["share"] = round(item["value"] * 100 / total, 1)
        return {
            "ranking": ranking,
            "workModes": [
                {
                    "label": item["label"],
                    "value": item["value"],
                    "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
                }
                for index, item in enumerate(modes)
            ],
            "supplierLevels": [
                {
                    "label": item["label"],
                    "value": item["value"],
                    "color": REPORT_COLORS[index % len(REPORT_COLORS)],
                }
                for index, item in enumerate(levels)
            ],
            "totalCompanies": len(companies),
            "totalPlans": total if companies else 0,
        }


def get_governance() -> dict:
    fields = [
        "文件名称",
        "文件编号",
        "制造单位",
        "流程状态",
        "创建时间",
        "发起人",
        "核安全报送级别",
        "合同号",
        "相关供方工作模式",
        "审查结论",
    ]
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] or 1
        fill_rates = []
        for field in fields:
            filled = conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE TRIM(COALESCE({qident(field)}, ''))!=''"
            ).fetchone()[0]
            fill_rates.append(
                {
                    "field": field,
                    "filled": int(filled),
                    "missing": int(total - filled),
                    "rate": round(filled * 100 / total, 1),
                }
            )
        batches = conn.execute(
            """
            SELECT sync_batch_id AS batchId,
                   COUNT(*) AS changeCount,
                   COUNT(DISTINCT "文件编号") AS documentCount,
                   MIN(changed_at) AS startedAt,
                   MAX(changed_at) AS finishedAt
            FROM document_changes
            GROUP BY sync_batch_id
            ORDER BY MAX(id) DESC
            LIMIT 20
            """
        ).fetchall()
        recent = conn.execute(
            f"""
            SELECT
              {qident('文件编号')} AS code,
              field_name AS fieldName,
              old_value AS oldValue,
              new_value AS newValue,
              changed_at AS changedAt,
              source_file AS sourceFile,
              sync_batch_id AS syncBatchId
            FROM document_changes
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        info = meta(conn)
        return {
            "meta": info,
            "fillRates": fill_rates,
            "syncBatches": [dict(row) for row in batches],
            "recentChanges": [dict(row) for row in recent],
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def export_rows(project: str, group: str, period: str, status: str, q: str) -> list[dict]:
    where, params = build_filters(project, group, period, status, q)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
              {qident('文件名称')} AS name,
              {qident('文件编号')} AS code,
              {qident('制造单位')} AS company,
              {qident('流程状态')} AS status,
              {qident('创建时间')} AS date,
              {qident('适用机组号')} AS unit,
              {qident('核安全报送级别')} AS reportLevel,
              {qident('合同号')} AS contractNo
            FROM documents
            WHERE {where}
            ORDER BY {qident('创建时间')} DESC, {qident('文件编号')} DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
