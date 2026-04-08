import gleam/option.{type Option, None, Some}
import team2form_gleam/modes.{
  Compat,
  DocsRecommended,
  LiveCompat,
  Paper,
  PaperBalanced,
  type Mode,
  type WeightPreset,
}

pub type Weights {
  Weights(alpha: Float, beta: Float, gamma: Float, delta: Float)
}

pub fn total(weights: Weights) -> Float {
  weights.alpha +. weights.beta +. weights.gamma +. weights.delta
}

pub fn normalized(weights: Weights) -> Weights {
  let all = total(weights)

  case all <=. 0.0 {
    True -> weights
    False ->
      Weights(
        alpha: weights.alpha /. all,
        beta: weights.beta /. all,
        gamma: weights.gamma /. all,
        delta: weights.delta /. all,
      )
  }
}

pub fn preset_weights(preset: WeightPreset) -> Weights {
  case preset {
    LiveCompat -> Weights(alpha: 0.3, beta: 0.3, gamma: 0.2, delta: 0.2)
    DocsRecommended -> Weights(alpha: 0.4, beta: 0.3, gamma: 0.2, delta: 0.1)
    PaperBalanced -> Weights(alpha: 0.25, beta: 0.25, gamma: 0.25, delta: 0.25)
  }
}

pub fn default_preset_for_mode(mode: Mode) -> WeightPreset {
  case mode {
    Paper -> PaperBalanced
    Compat -> LiveCompat
  }
}

pub fn resolve_weights(
  alpha alpha: Option(Float),
  beta beta: Option(Float),
  gamma gamma: Option(Float),
  delta delta: Option(Float),
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize normalize: Bool,
) -> Weights {
  let base =
    case preset {
      Some(chosen) -> preset_weights(chosen)
      None -> preset_weights(default_preset_for_mode(mode))
    }

  let weights = Weights(
    alpha: option.unwrap(alpha, base.alpha),
    beta: option.unwrap(beta, base.beta),
    gamma: option.unwrap(gamma, base.gamma),
    delta: option.unwrap(delta, base.delta),
  )

  case normalize {
    True -> normalized(weights)
    False -> weights
  }
}
