"""SQL-free compatibility facade for legacy media-access callers."""

from app.domains.media_access import service


class MediaAccessCompat:
    def update_all_lib_flag(self, *args, **kwargs):
        return service.update_all_lib_flag(*args, **kwargs)

    def check_download_unlock(self, tg_id: int, service_name: str) -> dict:
        return service.check_download_unlock(tg_id, service_name)

    def set_download_unlocked(self, tg_id: int, service_name: str) -> bool:
        return service.set_download_unlocked(tg_id, service_name)

    def deduct_credits_for_download_unlock(self, tg_id: int) -> tuple[bool, str, float]:
        return service.deduct_credits_for_download_unlock(tg_id)

    def get_download_unlocked_users_num(self) -> int:
        return service.get_download_unlocked_users_num()


__all__ = ["MediaAccessCompat"]
