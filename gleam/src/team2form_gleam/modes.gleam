pub type Mode {
  Compat
  Paper
}

pub type WeightPreset {
  LiveCompat
  DocsRecommended
  PaperBalanced
}

pub fn mode_from_string(value: String) -> Result(Mode, String) {
  case value {
    "compat" -> Ok(Compat)
    "paper" -> Ok(Paper)
    _ -> Error("Unknown mode: " <> value)
  }
}

pub fn mode_to_string(mode: Mode) -> String {
  case mode {
    Compat -> "compat"
    Paper -> "paper"
  }
}

pub fn weight_preset_from_string(value: String) -> Result(WeightPreset, String) {
  case value {
    "live_compat" -> Ok(LiveCompat)
    "docs_recommended" -> Ok(DocsRecommended)
    "paper_balanced" -> Ok(PaperBalanced)
    _ -> Error("Unknown weight preset: " <> value)
  }
}

pub fn weight_preset_to_string(preset: WeightPreset) -> String {
  case preset {
    LiveCompat -> "live_compat"
    DocsRecommended -> "docs_recommended"
    PaperBalanced -> "paper_balanced"
  }
}
