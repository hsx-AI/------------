from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import queries
from .db import resolve_db_path


app = FastAPI(title="核电质量计划看板 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    db_path = resolve_db_path()
    return {
        "ok": db_path.exists(),
        "dbPath": str(db_path),
        "message": "ready" if db_path.exists() else "database missing",
    }


@app.get("/api/filters")
def filters() -> dict:
    return queries.get_filter_options()


@app.get("/api/overview")
def overview(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_overview(project, group, period)


@app.get("/api/documents")
def documents(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
    status: str = Query("全部"),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
) -> dict:
    return queries.get_documents(project, group, period, status, q, page, pageSize)


@app.get("/api/trace")
def trace(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_trace(project, group, period)


@app.get("/api/suppliers")
def suppliers(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_suppliers(project, group, period)


@app.get("/api/governance")
def governance() -> dict:
    return queries.get_governance()


@app.get("/api/export")
def export_csv(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
    status: str = Query("全部"),
    q: str = Query(""),
) -> StreamingResponse:
    rows = queries.export_rows(project, group, period, status, q)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["文件名称", "文件编号", "制造单位", "流程状态", "创建时间", "适用机组号", "核安全报送级别", "合同号"])
    for row in rows:
        writer.writerow(
            [
                row["name"],
                row["code"],
                row["company"],
                row["status"],
                row["date"],
                row["unit"],
                row["reportLevel"],
                row["contractNo"],
            ]
        )
    payload = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nuclear-quality-plans.csv"'},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("dashboard_api.main:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
