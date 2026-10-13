"""Gmail newsletter intel (optional source — the 'your market pulse' layer).

Reads retailer/brand newsletters from your Gmail (Kicks, Lyko, Sephora,
Hunkemöller, H&M, Lindex, ASOS, Gina Tricot...) via the official Gmail API
with read-only OAuth, extracts trend phrases from subject lines, and stores
them through the SAME lexicon gates as the vertical harvests.

Setup (one time, on your Mac):
  1. console.cloud.google.com → new project 'trend-intel'
  2. APIs & Services → enable 'Gmail API'
  3. OAuth consent screen → External → add yourself as test user
  4. Credentials → 'OAuth client ID' → Desktop app → download JSON
  5. save it as  config/gmail_credentials.json
  6. first run opens a browser to authorize (read-only scope)
     → token cached in config/gmail_token.json

Without credentials.json this source is a silent no-op.
"""
import base64
import json
import re
import logging
import time
from pathlib import Path

log = logging.getLogger("trend_intel.gmail")

BASE = Path(__file__).resolve().parent.parent
# accept the common Google download names — rename nothing
CREDENTIALS = next((BASE / "config" / n for n in
                    ("gmail_credentials.json", "credentials.json",
                     "client_secret.json")
                    if (BASE / "config" / n).exists()), None)
TOKEN = BASE / "config" / "gmail_token.json"

# sender domains → vertical (retailer newsletters we want intel from)
SENDER_MAP = {
    "kicks": "beauty", "lyko": "beauty", "sephora": "beauty",
    "rituals": "beauty", "bodyshop": "beauty", "yvesrocher": "beauty",
    "cultbeauty": "beauty", "douglas": "beauty",
    "hunkemoller": "adult", "hunkemöller": "adult",
    "lindex": "adult", "victoriassecret": "adult", "vs": "adult",
    "intimissimi": "adult", "calzedonia": "adult", "changecom": "adult",
    "triumph": "adult", "passionata": "adult", "asos": "adult",
    "hm": "adult", "h&m": "adult", "ginatricot": "fashion",
}

SUBJECT_PREFIX_RE = re.compile(
    r"^(re:|fwd:|fw:|nyheter!?|new in[:!]?|newsletter[:!]?|\W+)+", re.I)


def _subject_clean(subject):
    t = SUBJECT_PREFIX_RE.sub("", subject or "").strip()
    # strip promo percentages / "X% off" tails
    t = re.sub(r"\b\d{1,2}\s?%\s?(off|rabatt|rea)\b.*$", "", t, flags=re.I).strip()
    # drop emoji-heavy or >70 char subjects (promos, not trends)
    if len(t) < 8 or len(t) > 70:
        return None
    return t


def _vertical_for_sender(sender):
    s = (sender or "").lower()
    for key, vert in SENDER_MAP.items():
        if key in s:
            return vert
    return None


def _get_service():
    if CREDENTIALS is None:
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = None
        if TOKEN.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(None)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS), SCOPES)  # type: ignore[arg-type]
                creds = flow.run_local_server(port=0)
            TOKEN.write_text(creds.to_json())
        return build("gmail", "v1", credentials=creds)
    except Exception as e:  # noqa: BLE001
        log.warning("gmail unavailable: %s", e)
        return None


def harvest(db, verbose=False, max_messages=60):
    """Pull recent newsletters, gate subject phrases, store as intel.

    Returns count stored. Silent no-op when credentials are missing or
    the Gmail API libraries aren't installed."""
    svc = _get_service()
    if svc is None:
        if verbose:
            print("[gmail] no credentials — skipping (see sources/gmail_newsletters.py header)")
        return 0
    from .verticals import gate_beauty, gate_adult
    count = 0
    try:
        # last 7 days, only inbox
        query = "category:promotions newer_than:7d"
        res = svc.users().messages().list(
            userId="me", q=query, maxResults=max_messages).execute()
        for msg in (res.get("messages") or []):
            try:
                m = svc.users().messages().get(
                    userId="me", id=msg["id"],
                    metadataHeaders=["Subject", "From"],
                    format="metadata").execute()
                headers = {h["name"].lower(): h["value"]
                           for h in m.get("payload", {}).get("headers", [])}
                sender = headers.get("from", "")
                vert = _vertical_for_sender(sender)
                if not vert:
                    continue
                title = _subject_clean(headers.get("subject", ""))
                if not title:
                    continue
                if vert == "beauty" and not gate_beauty(title):
                    continue
                if vert == "adult" and not gate_adult(title):
                    continue
                db.upsert_raw(
                    source="gmail_newsletter",
                    title=title,
                    external_id=title.lower()[:200],
                    extra={"vertical": vert, "sender": sender[:80],
                           "trusted": True},
                )
                count += 1
            except Exception:  # noqa: BLE001
                continue
            time.sleep(0.3)  # API politeness
    except Exception as e:  # noqa: BLE001
        log.warning("gmail harvest failed: %s", e)
    if verbose:
        print(f"[gmail] {count} gated newsletter phrases")
    return count
