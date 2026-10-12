from bot.detectors.base import Candidate, Detector, Frame
from bot.detectors.orb import ORB
from bot.detectors.trend_pullback import TrendPullback
from bot.detectors.vwap_reclaim import VWAPReclaim

ALL_DETECTORS: list[Detector] = [ORB(), VWAPReclaim(), TrendPullback()]

__all__ = ["ALL_DETECTORS", "ORB", "Candidate", "Detector", "Frame", "TrendPullback", "VWAPReclaim"]
