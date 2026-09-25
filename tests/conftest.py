"""锦标赛测试夹具：把 SQLAlchemy 会话绑到隔离的内存 SQLite。

不改 `settings.DB_URL`、不碰 `data/`。`get_session()` 在调用时读取
`SessionLocal`，故重绑模块属性即可让 `DatabaseORM` 单例打到测试库。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.databases.db import DatabaseORM
from app.domains.blackjack.models import BlackjackTournament, BlackjackTournamentEntry
from app.domains.identity.models import Statistics
from app.model_registry import metadata


@pytest.fixture
def session_env():
    """每个用例一张干净的内存库，并重绑 `app.databases.session`。"""
    import app.core.db as session_mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    previous_engine = session_mod.engine
    previous_factory = session_mod.SessionLocal
    session_mod.engine = engine
    session_mod.SessionLocal = factory

    yield engine

    session_mod.engine = previous_engine
    session_mod.SessionLocal = previous_factory
    engine.dispose()


@pytest.fixture
def orm(session_env) -> DatabaseORM:
    return DatabaseORM()


def _now_ms() -> int:
    return int(time.time() * 1000)


_next_id = 0


def next_id() -> int:
    """SQLite 上 BIGINT 主键不会 AUTOINCREMENT，测试行必须显式给 id。"""
    global _next_id
    _next_id += 1
    return _next_id


def add_user(orm: DatabaseORM, tg_id: int, credits: float = 100.0) -> None:
    from app.core.db import get_session

    with get_session() as session:
        session.add(Statistics(tg_id=int(tg_id), donation=0, credits=float(credits)))


def add_tournament(
    orm: DatabaseORM,
    *,
    status: int | None = None,
    play_deadline_ms: int | None = None,
    register_deadline_ms: int | None = None,
    entrant_count: int = 2,
    buy_in_credits: int = 30,
    rake_bp: int = 0,
    total_hands: int = 2,
    min_bet_chips: int = 10,
    title: str = "test tournament",
) -> dict:
    from app.core.db import get_session

    now = _now_ms()
    if register_deadline_ms is None:
        register_deadline_ms = now - 2 * 3600 * 1000
    if play_deadline_ms is None:
        play_deadline_ms = now + 2 * 3600 * 1000
    if status is None:
        status = orm.TOURNAMENT_RUNNING

    with get_session() as session:
        tournament = BlackjackTournament(
            id=next_id(),
            title=title,
            status=int(status),
            buy_in_credits=int(buy_in_credits),
            starting_chips=1000,
            total_hands=int(total_hands),
            min_bet_chips=int(min_bet_chips),
            max_bet_chips=500,
            bet_step_chips=10,
            min_entrants=2,
            max_entrants=20,
            entrant_count=int(entrant_count),
            rake_bp=int(rake_bp),
            seeded_prize_credits=0,
            payout_structure="[50, 30, 20]",
            dealer_hits_soft_17=0,
            blackjack_payout=1.5,
            surrender_enabled=1,
            hand_timeout_minutes=15,
            register_deadline_ms=int(register_deadline_ms),
            play_deadline_ms=int(play_deadline_ms),
        )
        session.add(tournament)
        session.flush()
        return orm._tournament_to_dict(tournament)


def add_entry(
    orm: DatabaseORM,
    tournament_id: int,
    tg_id: int,
    *,
    status: int | None = None,
    chips: int = 1000,
    hands_played: int = 0,
    registered_at_ms: int | None = None,
) -> dict:
    from app.core.db import get_session

    if status is None:
        status = orm.ENTRY_PLAYING
    if registered_at_ms is None:
        registered_at_ms = _now_ms()

    with get_session() as session:
        entry = BlackjackTournamentEntry(
            id=next_id(),
            tournament_id=int(tournament_id),
            tg_id=int(tg_id),
            chips=int(chips),
            hands_played=int(hands_played),
            status=int(status),
            registered_at_ms=int(registered_at_ms),
        )
        session.add(entry)
        session.flush()
        return orm._tournament_entry_to_dict(entry)


def add_pending_hand(
    orm: DatabaseORM,
    tournament_id: int,
    tg_id: int,
    *,
    bet_chips: int = 10,
) -> int:
    """插入一手未终结的赛内牌，供结算复检使用。"""
    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand
    from app.domains.blackjack.rules import STATUS_PLAYER_TURN

    with get_session() as session:
        hand = BlackjackHand(
            id=next_id(),
            tg_id=int(tg_id),
            tournament_id=int(tournament_id),
            status=STATUS_PLAYER_TURN,
            bet_credits=int(bet_chips),
            doubled=0,
            deck_seed="00" * 16,
            next_card_index=4,
            player_cards='["AS", "7H"]',
            dealer_cards='["KD", "5C"]',
            rake_bp_on_profit=0,
            rake_jackpot_bp=0,
            blackjack_payout=1.5,
            dealer_hits_soft_17=0,
            hand_timeout_minutes=15,
            surrender_enabled=1,
            rake_waived=0,
            created_at_ms=_now_ms(),
        )
        session.add(hand)
        session.flush()
        return int(hand.id)


def add_cash_hand(
    orm: DatabaseORM,
    tg_id: int,
    *,
    player_cards: str = '["KH", "5C", "9H"]',
    dealer_cards: str = '["KD", "5C"]',
    bet_credits: int = 15,
    doubled: int = 0,
    created_at_ms: int | None = None,
    surrender_enabled: int = 1,
    tournament_id: int | None = None,
) -> int:
    """插入一手未终结的现金局手牌，牌面由用例指定以控制结算结果。

    常用牌面组合（庄家无需补牌、结果确定）：
    - 判负（爆牌）：player=["KH","5C","9H"]（24 点，庄家不补牌）
    - 判胜：player=["QH","JH"]（20）vs dealer=["KH","9H"]（19，停牌）
    - 平局：player=["QH","9H"]（19）vs dealer=["KH","9H"]（19，停牌）
    - 天胡：player=["AS","KH"]（natural，庄家不补牌）

    `tournament_id` 非空时为赛内手牌（注额语义为筹码），供验证赛内
    手牌不进入留存机制的计数。
    """
    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand
    from app.domains.blackjack.rules import STATUS_PLAYER_TURN

    with get_session() as session:
        hand = BlackjackHand(
            id=next_id(),
            tg_id=int(tg_id),
            tournament_id=tournament_id,
            status=STATUS_PLAYER_TURN,
            bet_credits=int(bet_credits),
            doubled=int(doubled),
            deck_seed="00" * 16,
            next_card_index=4,
            player_cards=player_cards,
            dealer_cards=dealer_cards,
            # 抽水置零：留存测试不关心抽水，而奖池行的 SystemConfig 插入在
            # SQLite 测试库上无自增主键会直接失败（与生产无关）
            rake_bp_on_profit=0,
            rake_jackpot_bp=0,
            blackjack_payout=1.5,
            dealer_hits_soft_17=0,
            hand_timeout_minutes=15,
            surrender_enabled=int(surrender_enabled),
            rake_waived=0,
            created_at_ms=created_at_ms or _now_ms(),
        )
        session.add(hand)
        session.flush()
        return int(hand.id)


def get_stats(tg_id: int) -> dict:
    """读取该用户 Statistics 行的快照（含留存机制的新列）。

    返回普通字典而非 ORM 实例：get_session() 关闭后实例即脱离会话，
    惰性刷新会抛 DetachedInstanceError。
    """
    from app.core.db import get_session

    with get_session() as session:
        stats = session.get(Statistics, int(tg_id))
        assert stats is not None
        return {
            "credits": float(stats.credits),
            "tournament_wallet_credits": float(stats.tournament_wallet_credits),
            "blackjack_lose_streak": int(stats.blackjack_lose_streak),
            "blackjack_hands_since_freespin": int(stats.blackjack_hands_since_freespin),
        }
