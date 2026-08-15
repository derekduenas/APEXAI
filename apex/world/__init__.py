"""Track 4: the World State Engine (Build Directive v4.0 section 2).

Converts information into STRUCTURED STATE VARIABLES -- causal, online,
PIT-correct, vintage-aware. It does not forecast, branch, or simulate (the
Twin is gated), and it is NOT a regime-selection optimizer: this package
answers "what state was the market in, knowably, at time t" and refuses to
answer "which state made money". Conditional-expectancy questions ("GP works
only in state X") are NEW HYPOTHESES that go through the full registration
machinery -- a deliberate structural refusal, not an omission.
"""
