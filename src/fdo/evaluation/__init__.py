"""Değerlendirme (backtest) çerçevesi (README §13.1, V2): değerlendiriciler ve strateji karşılaştırması."""

from fdo.evaluation.evaluators import GameLogEvaluator, ProjectionNoiseEvaluator
from fdo.evaluation.interface import EvaluationResult, SeasonEvaluator

__all__ = ["EvaluationResult", "GameLogEvaluator", "ProjectionNoiseEvaluator", "SeasonEvaluator"]
