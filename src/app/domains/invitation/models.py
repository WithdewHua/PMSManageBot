from sqlalchemy import BIGINT, SMALLINT, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Invitation(Base):
    """Invitation code model"""

    __tablename__ = "invitation"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[int] = mapped_column(
        BIGINT, index=True, nullable=False, info={"tg_id": "user"}
    )
    is_used: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    is_privileged: Mapped[int] = mapped_column(
        SMALLINT, default=0, server_default=text("0"), nullable=False
    )
    used_by: Mapped[str | None] = mapped_column(
        String, nullable=True, info={"tg_id": False}
    )
    service: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Service used for redemption: plex, emby; NULL if not yet used
    plex_id: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Plex user ID after redemption
    emby_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Emby user ID after redemption
