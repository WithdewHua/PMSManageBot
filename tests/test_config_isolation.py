from pathlib import Path

from app.core.config import settings


def test_tests_do_not_read_repository_data_env() -> None:
    repository_data = Path(__file__).parents[1] / "data"
    assert settings.DATA_PATH != repository_data
    assert settings.ENV_FILE_PATH.parent != repository_data
    assert not settings.ENV_FILE_PATH.exists()


def test_removed_business_env_keys_are_ignored() -> None:
    from app.core.config import Settings

    isolated = Settings(PLEX_REGISTER=True, INVITATION_CREDITS=999)
    assert not hasattr(isolated, "PLEX_REGISTER")
    assert not hasattr(isolated, "INVITATION_CREDITS")
