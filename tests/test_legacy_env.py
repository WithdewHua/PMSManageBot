from __future__ import annotations

from pathlib import Path

from app.core.legacy_env import LegacyEnvSource


def test_legacy_env_precedence_and_codecs(tmp_path: Path) -> None:
    working = tmp_path / "working.env"
    data = tmp_path / "data.env"
    working.write_text(
        "FLAG = false\nCOUNT=2\nITEMS=work-a, work-b\nDUP=working\n",
        encoding="utf-8",
    )
    data.write_text("FLAG=true\nDUP=data\n", encoding="utf-8")
    source = LegacyEnvSource(
        {"FLAG": False, "COUNT": 0, "ITEMS": [], "DUP": "default"},
        data_path=data,
        working_path=working,
        environ={"COUNT": "3", "ITEMS": "env-a,env-b"},
    )

    assert source.read("FLAG") is True
    assert source.read("COUNT") == 3
    assert source.read("ITEMS") == ["env-a", "env-b"]
    assert source.read("DUP") == "data"


def test_legacy_env_repeated_keys_and_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("VALUE=first\nVALUE=second\n", encoding="utf-8")
    source = LegacyEnvSource(
        {"VALUE": "default"}, data_path=None, working_path=path, environ={}
    )
    assert source.read("VALUE") == "second"

    path.write_text("VALUE=ok\nmalformed\n", encoding="utf-8")
    assert source.read("VALUE") == "ok"


def test_legacy_env_missing_key_uses_code_default(tmp_path: Path) -> None:
    source = LegacyEnvSource(
        {"FLAG": False}, data_path=tmp_path / "missing", working_path=tmp_path / "none"
    )
    assert source.read("FLAG") is False
    assert source.present_keys() == set()
