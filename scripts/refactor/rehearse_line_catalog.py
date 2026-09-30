"""Production-shaped local rehearsal for line-catalog migration and persistence."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", required=True, help="PostgreSQL URL for disposable rehearsal"
    )
    args = parser.parse_args()

    if not args.url.startswith("postgresql"):
        raise SystemExit("rehearsal requires a PostgreSQL URL")

    temp_dir = tempfile.mkdtemp(prefix="pms-rehearsal-lines-")
    os.environ.update(
        {
            "DATABASE_URL": args.url,
            "DATABASE_TYPE": "postgresql",
            "DATA_DIR": temp_dir,
            "TZ": "UTC",
        }
    )

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.core import kv as core_kv
    from app.core.legacy_env import LegacyEnvSource
    from app.domains.lines import catalog
    from app.model_registry import metadata

    engine = create_engine(args.url, pool_size=10, max_overflow=10, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # 1. Setup production baseline lines in LegacyEnvSource and SystemConfig
    prod_normal_lines = [
        "kr1.stream.funmedia.10101.io",
        "jp1.stream.funmedia.10101.io",
        "funmedia.domob.org",
        "sg.funmedia.domob.org",
        "de1.stream.funmedia.10101.io",
        "jp2.stream.funmedia.10101.io",
        "auto.funmedia.domoo.xyz",
        "tyo.funmedia.domoo.xyz",
        "gd.funmedia.domoo.xyz",
        "tyo.funmedia.domob.org",
    ]
    prod_premium_lines = [
        "46ef77f131.hk.stream.funmedia.10101.io",
        "72d4a47884.us1.stream.funmedia.10101.io",
        "8213d5b64b.us2.stream.funmedia.10101.io",
        "46ef77f131.sg.stream.funmedia.10101.io",
        "1f1095841b.jp3.funmedia.stream",
    ]

    # Pre-migration KV: add some valid tags, one free premium line, plus orphan entries
    core_kv.upsert("line_tag", "kr1.stream.funmedia.10101.io", "快速, 亚洲")
    core_kv.upsert("line_tag", "orphan.line.example.com", "孤儿标签")
    core_kv.upsert("free_premium_line", "46ef77f131.hk.stream.funmedia.10101.io", "1")
    core_kv.upsert("free_premium_line", "orphan.premium.example.com", "1")

    legacy_source = LegacyEnvSource(
        defaults={
            "STREAM_BACKEND": list(prod_normal_lines),
            "PREMIUM_STREAM_BACKEND": list(prod_premium_lines),
        }
    )

    # 2. Run one-time import
    print("--- 步骤 1：执行首次目录导入 ---")
    catalog.invalidate_cache()
    imported = catalog.import_legacy_line_catalog_if_needed(legacy_source)
    assert imported is True, "First import should succeed"

    # Verify catalog matches baseline lists
    imported_normals = catalog.normal_lines()
    imported_premiums = catalog.premium_lines()
    assert imported_normals == prod_normal_lines, (
        f"Normal lines mismatch: {imported_normals}"
    )
    assert imported_premiums == prod_premium_lines, (
        f"Premium lines mismatch: {imported_premiums}"
    )
    assert catalog.free_premium_lines() == ["46ef77f131.hk.stream.funmedia.10101.io"]
    assert catalog.line_tags("kr1.stream.funmedia.10101.io") == ["快速", "亚洲"]
    assert catalog.line_tags("orphan.line.example.com") == []

    # Verify old KV deleted and marker present
    assert core_kv.get_all("line_tag") == {}
    assert core_kv.get_all("free_premium_line") == {}
    assert core_kv.get("lines", "catalog_imported") is not None
    print(
        f"导入核对成功：{len(imported_normals)} 条普通线路，{len(imported_premiums)} 条高级线路。"
    )
    print(
        "跳过清单记录：跳过 1 条孤儿标签 (orphan.line.example.com)，跳过 1 条孤儿免费标记 (orphan.premium.example.com)。"
    )

    # 3. Modify catalog in admin workflow
    print("\n--- 步骤 2：后台维护操作（新增、删除、改标签、改免费线路）---")
    catalog.add_line("new.normal.line.com", premium=False)
    catalog.add_line("new.premium.line.com", premium=True)
    catalog.delete_line("auto.funmedia.domoo.xyz", premium=False)
    catalog.set_line_tags("new.normal.line.com", ["测试", "4K"])
    catalog.set_free_premium_lines(["new.premium.line.com"])

    # Verify modifications are immediately visible
    assert "new.normal.line.com" in catalog.normal_lines()
    assert "new.premium.line.com" in catalog.premium_lines()
    assert "auto.funmedia.domoo.xyz" not in catalog.normal_lines()
    assert catalog.line_tags("new.normal.line.com") == ["测试", "4K"]
    assert catalog.free_premium_lines() == ["new.premium.line.com"]
    print("修改操作立即可见验证通过。")

    # 4. Simulate service restart
    print("\n--- 步骤 3：模拟服务重启与持久化验证 ---")
    catalog.invalidate_cache()
    db_module.engine.dispose()
    new_engine = create_engine(
        args.url, pool_size=10, max_overflow=10, pool_pre_ping=True
    )
    db_module.engine = new_engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=new_engine
    )

    # Re-run startup import hook
    re_imported = catalog.import_legacy_line_catalog_if_needed(legacy_source)
    assert re_imported is False, "Repeated startup import must skip"

    # Verify all modifications remain intact after restart
    restarted_normals = catalog.normal_lines()
    restarted_premiums = catalog.premium_lines()
    assert "new.normal.line.com" in restarted_normals
    assert "new.premium.line.com" in restarted_premiums
    assert "auto.funmedia.domoo.xyz" not in restarted_normals
    assert catalog.line_tags("new.normal.line.com") == ["测试", "4K"]
    assert catalog.free_premium_lines() == ["new.premium.line.com"]
    print("重启后数据保持验证通过！")

    print("\n==========================================")
    print("生产形态本地彩排顺利完成，所有断言验证通过！")
    print("==========================================")
    new_engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
