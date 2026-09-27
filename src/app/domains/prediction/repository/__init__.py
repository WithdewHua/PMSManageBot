from .part_1 import _PredictionRepositoryPart1
from .part_2 import _PredictionRepositoryPart2


class PredictionRepository(_PredictionRepositoryPart1, _PredictionRepositoryPart2):
    pass


from .part_1 import count_bets_tx as count_bets_tx

__all__ = ["PredictionRepository", "count_bets_tx"]
