from __future__ import annotations

import argparse
from pathlib import Path

import ecs_auto_login
import excel_db
from scheduler_settings import load_scheduler_config, resolve_db_path


def sync_once(*, prefer_saved_session: bool, db_path: Path, keep_excel: bool) -> dict:
    if prefer_saved_session:
        ecs_auto_login.log("使用已保存会话下载 Excel")
        excel_path = ecs_auto_login.download_with_saved_session()
        used_session = True
    else:
        excel_path = ecs_auto_login.run()
        used_session = False

    stats = excel_db.upsert_excel(db_path, excel_path)
    ecs_auto_login.log(
        "数据库更新完成："
        f"总数={stats['total']}，新增={stats['inserted']}，"
        f"更新={stats['updated']}，未变化={stats['unchanged']}，"
        f"变更字段数={stats['changed_fields']}，"
        f"批次={stats['sync_batch_id']}，库={db_path}"
    )
    if not keep_excel:
        try:
            excel_path.unlink(missing_ok=True)
            ecs_auto_login.log(f"已删除临时 Excel: {excel_path}")
        except OSError as exc:
            ecs_auto_login.log(f"删除 Excel 失败（可忽略）: {exc}")
    return {**stats, "excel": str(excel_path), "usedSession": used_session}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载 AE Excel 并按文件编号 upsert 到 SQLite")
    parser.add_argument(
        "--prefer-session",
        action="store_true",
        help="仅使用已保存会话下载；失败直接退出，由 scheduler 决定是否完整登录",
    )
    parser.add_argument("--db", help="SQLite 数据库路径，默认读 scheduler_config.json")
    parser.add_argument(
        "--delete-excel",
        action="store_true",
        help="入库后删除本次下载的 Excel",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_scheduler_config()
    db_path = Path(args.db) if args.db else resolve_db_path(config)
    keep_excel = True if not args.delete_excel else False
    if not args.delete_excel:
        keep_excel = bool(config.get("keepDownloadedExcel", True))
    sync_once(
        prefer_saved_session=bool(args.prefer_session),
        db_path=db_path,
        keep_excel=keep_excel,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", flush=True)
        raise SystemExit(1)
