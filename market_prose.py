"""Shared estimative-prose primitives for Asifah Market Watch detectors.

One desk, one voice. Every Market Watch detector -- conflict repricing, market
fragility, and any future market module -- sources its disclaimer frame and its
historical-analog caveat from here, so the convergence-not-prediction voice is
defined once and cannot drift between modules.

Voice conventions (convergence, NOT prediction):
  * Describe what informed capital appears to be pricing and what the present
    pattern resembles historically. Never probabilities, dates, or "will".
  * A coherent tape or a close historical analog describes present conditions,
    not an outcome. The reader completes the inference.

ASCII-only. No third-party imports -- safe to import from any backend module.
"""

VERSION = '1.0.0'


def market_disclaimer(subject, forecast_of, coda):
    """Canonical Market Watch convergence-not-prediction disclaimer.

    One frame, defined here so every Market Watch detector reads as one desk:

        "This is a CONVERGENCE read of <subject>, NOT a forecast<forecast_of>
         and NOT investment advice. <coda>"

    subject     : what the read is OF, e.g. 'market positioning',
                  'endogenous market fragility'.
    forecast_of : narrows the forecast negation, e.g. ' of whether the off-ramp
                  holds', ' of whether or when a drawdown occurs'. '' is allowed.
    coda        : the detector-specific closing sentence(s) -- carries the
                  reader-completes-the-inference / describes-present-conditions
                  language particular to that detector.
    """
    return ("This is a CONVERGENCE read of " + subject + ", NOT a forecast"
            + forecast_of + " and NOT investment advice. " + coda)


def analog_tail():
    """Canonical caveat appended to any historical-analog or lead-time line."""
    return ("Historical lead times are descriptive of past episodes only; "
            "they are not a forecast.")
