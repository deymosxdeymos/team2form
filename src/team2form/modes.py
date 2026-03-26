from enum import StrEnum


class Mode(StrEnum):
    COMPAT = 'compat'
    PAPER = 'paper'


class WeightPreset(StrEnum):
    LIVE_COMPAT = 'live_compat'
    DOCS_RECOMMENDED = 'docs_recommended'
    PAPER_BALANCED = 'paper_balanced'
