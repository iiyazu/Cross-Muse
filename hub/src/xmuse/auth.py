"""Bearer tokens: HS256 JWTs signed with this workspace's key (tokens/_signing.key, 0600, made on first use).

Claims: iss "xmuse", sub (the member id, or "human"), kind ("admin" | "member" | "operator"), iat, jti. No expiry:
a member's token lives in tokens/<id> for as long as the member does, and its MCP shim reads it once at start.
The signature proves the hub issued the token; the database still decides whether it is current: hub.db keeps the
sha256 of each live token (agents.token_digest, operators.token_digest; the admin's is read from tokens/_admin), so a
re-issued or removed member's old token is refused although its signature is good.
"""
import hashlib
import os
import secrets
import time
from pathlib import Path

import jwt

ISSUER = "xmuse"
ALGORITHM = "HS256"
KINDS = ("admin", "member", "operator")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def signing_key(state: Path) -> bytes:
    """The workspace's key; the first caller creates it (O_EXCL: two processes racing get the same key)."""
    path = Path(state) / "tokens" / "_signing.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    for _ in range(50):  # the creator may not have written it yet
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key.encode()
        time.sleep(0.01)
    raise RuntimeError(f"{path} is empty")


def mint(key: bytes, sub: str, kind: str) -> str:
    assert kind in KINDS, kind
    return jwt.encode({"iss": ISSUER, "sub": sub, "kind": kind, "iat": int(time.time()),
                       "jti": secrets.token_urlsafe(16)}, key, algorithm=ALGORITHM)


def claims(key: bytes, token: str) -> dict | None:
    """The claims of a token this hub signed, or None (bad signature, wrong issuer, missing claim, not a JWT)."""
    try:
        c = jwt.decode(token, key, algorithms=[ALGORITHM], issuer=ISSUER,
                       options={"require": ["iss", "sub", "kind", "jti"]})
    except jwt.InvalidTokenError:
        return None
    return c if c.get("kind") in KINDS and isinstance(c.get("sub"), str) else None


def bearer(header: str | None) -> str:
    return (header or "").removeprefix("Bearer ").strip()


def issue(state: Path, sub: str, kind: str) -> str:
    """A new token for `sub`, written to tokens/<sub> (tokens/_admin for the user), 0600. Returns it."""
    tok = mint(signing_key(state), sub, kind)
    path = Path(state) / "tokens" / ("_admin" if kind == "admin" else sub)
    path.write_text(tok, encoding="utf-8")
    path.chmod(0o600)
    return tok


def migrate(state: Path, conn) -> list[str]:
    """Opaque tokens from before JWT (xmt_...): re-issued as JWTs, digests updated. Returns who got a new token;
    their running MCP shims read the old one at start and need a restart."""
    from . import db
    out, tokens = [], Path(state) / "tokens"
    admin = tokens / "_admin"
    if admin.exists() and admin.read_text(encoding="utf-8").strip().count(".") != 2:
        issue(state, "human", "admin")
        out.append("human")
    for aid, in conn.execute("select id from agents where removed=0").fetchall():
        f = tokens / aid
        if f.exists() and f.read_text(encoding="utf-8").strip().count(".") != 2:
            tok = issue(state, aid, "member")
            with db.tx(conn):
                conn.execute("update agents set token_digest=? where id=?", (digest(tok), aid))
            out.append(aid)
    return out
