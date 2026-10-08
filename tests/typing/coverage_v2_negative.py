"""Each EXPECT_ERROR line must be rejected; do not execute this file."""
from xreactor.declarative import Bin, BinRule, CoverPoint
from coverage_v2_positive import Coverage, Sample, StatePoint, TakenPoint, coverage, fields

coverage.sample({"state": 1, "taken": True})  # EXPECT_ERROR
coverage.sample(Sample("busy", True))  # EXPECT_ERROR
coverage.state.count(TakenPoint.yes)  # EXPECT_ERROR
StatePoint.buisy  # EXPECT_ERROR
Coverage.staet  # EXPECT_ERROR
fields.select(lambda sample: sample.staet)  # EXPECT_ERROR
StatePoint(source=fields.select(lambda sample: sample.label))  # EXPECT_ERROR
boolean_field = fields.select(lambda sample: sample.taken)
StatePoint(source=boolean_field)  # EXPECT_ERROR

class InvalidPoint(CoverPoint[int]):
    wrong: BinRule[int] = Bin.values("busy")  # EXPECT_ERROR
