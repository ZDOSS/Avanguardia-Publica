"""Fail-closed runtime control for legacy GovTrack profile enrichment."""

from __future__ import annotations

from collections.abc import Mapping


GOVTRACK_PROFILE_ENRICHMENT_MODE_ENV = "GOVTRACK_PROFILE_ENRICHMENT_MODE"
GOVTRACK_PROFILE_ENRICHMENT_DISABLED = "disabled"
GOVTRACK_PROFILE_ENRICHMENT_ENABLED = "enabled"


def govtrack_profile_enrichment_mode(environ: Mapping[str, str]) -> str:
    """Return the explicit legacy-profile mode, rejecting ambiguous opt-ins."""

    mode = str(environ.get(GOVTRACK_PROFILE_ENRICHMENT_MODE_ENV) or "").strip().lower()
    mode = mode or GOVTRACK_PROFILE_ENRICHMENT_DISABLED
    if mode not in {
        GOVTRACK_PROFILE_ENRICHMENT_DISABLED,
        GOVTRACK_PROFILE_ENRICHMENT_ENABLED,
    }:
        raise ValueError(
            f"{GOVTRACK_PROFILE_ENRICHMENT_MODE_ENV} must be 'disabled' or 'enabled'"
        )
    return mode
