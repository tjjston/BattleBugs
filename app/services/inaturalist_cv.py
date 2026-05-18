"""iNaturalist Computer Vision integration.

Wraps iNat's /v1/computervision/score_image endpoint, which scores a JPEG
of an arthropod against their species-recognition model trained on tens of
millions of research-grade observations. The endpoint requires an OAuth
bearer token issued to a registered iNaturalist application.

Configuration
-------------
Set INATURALIST_API_TOKEN in the environment (or as an admin SystemSetting
with key 'inaturalist_api_token'). When empty, the module reports
unavailable() == True and the classifier pipeline falls through to the
existing LLM path.

To obtain a token (one-time, ~5 minutes):
  1. Sign in at https://www.inaturalist.org
  2. Visit https://www.inaturalist.org/oauth/applications and "New
     Application". Redirect URI can be a localhost URL — we only need
     the password-grant flow for personal use.
  3. Run the password grant exchange (see docs/inaturalist_setup.md or
     curl example below) to swap your username + password + client_id
     for a bearer token. Tokens are long-lived (~1 year).
  4. Paste the token into .env as INATURALIST_API_TOKEN.

Curl example (replace placeholders):
  curl -sX POST https://www.inaturalist.org/oauth/token \\
       -d "grant_type=password" \\
       -d "client_id=YOUR_CLIENT_ID" \\
       -d "client_secret=YOUR_CLIENT_SECRET" \\
       -d "username=YOUR_INAT_USERNAME" \\
       -d "password=YOUR_INAT_PASSWORD"
"""

from __future__ import annotations

import os
import requests
from typing import Optional
from flask import current_app


_API_BASE = "https://api.inaturalist.org/v1"
_USER_AGENT = "BattleBugs/1.0 (taxonomy enrichment)"


def _token() -> Optional[str]:
    """Pull the iNat OAuth bearer token from env or SystemSetting."""
    tok = os.environ.get('INATURALIST_API_TOKEN')
    if tok:
        return tok.strip()
    try:
        from app.models import SystemSetting
        tok = SystemSetting.get('inaturalist_api_token')
        if tok:
            return tok.strip()
    except Exception:
        pass
    return None


def unavailable() -> bool:
    """True when no token is configured — caller should skip CV calls."""
    return not _token()


def score_image(image_bytes: bytes, *, lat: Optional[float] = None,
                lng: Optional[float] = None,
                taxon_id: int = 47120) -> Optional[list[dict]]:
    """Submit a single image to iNat CV and return the top candidates.

    Args:
        image_bytes: raw JPEG/PNG/WebP bytes
        lat, lng: optional location to bias the vision model toward
                  regional species (improves accuracy noticeably when known)
        taxon_id: scope the prediction to this iNat taxon and its descendants.
                  Default 47120 is Arthropoda — keeps mammals/birds/etc out
                  of the result set even if the photo looks ambiguous.

    Returns:
        A list of result dicts, each with:
          {scientific_name, common_name, rank, taxon_id, score (0-1),
           image_url, ancestor_ids}
        sorted by score descending. None on auth/network failure.
    """
    tok = _token()
    if not tok:
        return None

    files = {'image': ('upload.jpg', image_bytes, 'image/jpeg')}
    params: dict = {'taxon_id': taxon_id}
    if lat is not None and lng is not None:
        params['lat'] = lat
        params['lng'] = lng

    headers = {
        'Authorization': f"Bearer {tok}",
        'User-Agent': _USER_AGENT,
    }
    try:
        resp = requests.post(
            f"{_API_BASE}/computervision/score_image",
            files=files,
            data=params,
            headers=headers,
            timeout=30,
        )
    except Exception as exc:
        current_app.logger.warning("iNat CV score_image network error: %s", exc)
        return None

    if resp.status_code == 401:
        current_app.logger.warning(
            "iNat CV returned 401 Unauthorized — the configured INATURALIST_API_TOKEN "
            "is missing or expired. Falling back to local LLM classifier."
        )
        return None
    if not resp.ok:
        current_app.logger.warning("iNat CV %s: %s", resp.status_code, resp.text[:200])
        return None

    data = resp.json()
    out = []
    for res in data.get('results') or []:
        taxon = res.get('taxon') or {}
        photo = (taxon.get('default_photo') or {})
        out.append({
            'scientific_name': taxon.get('name'),
            'common_name': taxon.get('preferred_common_name'),
            'rank': taxon.get('rank'),
            'taxon_id': taxon.get('id'),
            'score': res.get('combined_score') or res.get('vision_score') or 0.0,
            'image_url': photo.get('medium_url') or photo.get('square_url'),
            'ancestor_ids': taxon.get('ancestor_ids') or [],
        })
    return out
