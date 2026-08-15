"""P1A: the intraday data foundation and historical event-replay kernel.

The goal of this package is not to produce a trade. It is to make it
extremely difficult for APEX to hallucinate one because its market history
was wrong. Everything here is provider-neutral: Massive is adapter V1 (and
fails closed until the operator's subscription exists); no vendor object is
a canonical domain object. All replay outputs are ENGINEERING/EXPLORATORY.

Constitutional rules carried from the directive:
  * raw data is immutable and unadjusted; adjustments are DERIVED layers;
  * ticker != identity; ambiguity fails closed;
  * absence of an observation is data -- a missing minute is never a fill;
  * no completed bar is visible before it would have completed;
  * same inputs -> same event stream -> same hash;
  * the BrokerAdapter is unreachable from replay.
"""
