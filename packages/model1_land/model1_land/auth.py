"""Demo-grade session: signed cookie holding investor_id. No password."""
from __future__ import annotations

from typing import Optional
from fastapi import Request, Depends
from itsdangerous import URLSafeSerializer, BadSignature
from sqlmodel import Session

from .db import get_session
from .models import Investor

COOKIE_NAME = "keheilan_session"
_SECRET = "keheilan-demo-secret"  # demo only — rotate in prod
_signer = URLSafeSerializer(_SECRET, salt="investor")


def make_session_cookie(investor_id: int) -> str:
    return _signer.dumps({"investor_id": investor_id})


def read_session_cookie(token: str) -> Optional[int]:
    try:
        data = _signer.loads(token)
        return int(data["investor_id"])
    except (BadSignature, KeyError, ValueError, TypeError):
        return None


def current_investor(request: Request,
                     session: Session = Depends(get_session)) -> Optional[Investor]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    iid = read_session_cookie(token)
    if iid is None:
        return None
    return session.get(Investor, iid)
