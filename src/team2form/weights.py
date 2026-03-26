from dataclasses import dataclass

from .modes import Mode, WeightPreset


@dataclass(frozen=True, slots=True)
class Weights:
    alpha: float
    beta: float
    gamma: float
    delta: float

    @property
    def total(self) -> float:
        return self.alpha + self.beta + self.gamma + self.delta

    def normalized(self) -> 'Weights':
        total = self.total
        if total <= 0:
            return self
        return Weights(
            alpha=self.alpha / total,
            beta=self.beta / total,
            gamma=self.gamma / total,
            delta=self.delta / total,
        )


PRESET_WEIGHTS: dict[WeightPreset, Weights] = {
    WeightPreset.LIVE_COMPAT: Weights(0.3, 0.3, 0.2, 0.2),
    WeightPreset.DOCS_RECOMMENDED: Weights(0.4, 0.3, 0.2, 0.1),
    WeightPreset.PAPER_BALANCED: Weights(0.25, 0.25, 0.25, 0.25),
}


def default_preset_for_mode(mode: Mode) -> WeightPreset:
    if mode == Mode.PAPER:
        return WeightPreset.PAPER_BALANCED
    return WeightPreset.LIVE_COMPAT


def resolve_weights(
    *,
    alpha: float | None,
    beta: float | None,
    gamma: float | None,
    delta: float | None,
    mode: Mode,
    preset: WeightPreset | None = None,
    normalize: bool = False,
) -> Weights:
    base = PRESET_WEIGHTS[preset or default_preset_for_mode(mode)]
    weights = Weights(
        alpha=base.alpha if alpha is None else alpha,
        beta=base.beta if beta is None else beta,
        gamma=base.gamma if gamma is None else gamma,
        delta=base.delta if delta is None else delta,
    )
    return weights.normalized() if normalize else weights
