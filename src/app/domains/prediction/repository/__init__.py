from .analytics import _PredictionRepositoryAnalytics
from .bets import _PredictionRepositoryBets
from .markets import _PredictionRepositoryMarkets
from .settlement import _PredictionRepositorySettlement


class PredictionRepository(
    _PredictionRepositoryMarkets,
    _PredictionRepositoryBets,
    _PredictionRepositorySettlement,
    _PredictionRepositoryAnalytics,
):
    """Private compatibility implementation."""


from .analytics import count_bets_tx as count_bets_tx

__all__ = ["PredictionRepository", "count_bets_tx"]
