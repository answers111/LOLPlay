"""Renew ChatGPT plan credentials without logging or exposing token values."""

import base64
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_THREAD_LOCK = threading.Lock()
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"


class OAuthRefreshError(RuntimeError):
    pass


@contextmanager
def _credential_lock(path):
    """Serialize rotating refresh tokens across threads and local processes."""
    with _THREAD_LOCK:
        with path.with_suffix(path.suffix + ".lock").open("a+b") as lock:
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            deadline = time.monotonic() + 60
            while True:
                try:
                    lock.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise OAuthRefreshError("Timed out waiting for OAuth credential refresh.") from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _expires_at(record):
    candidates = []
    if record.get("saved_at") is not None and record.get("expires_in") is not None:
        candidates.append(float(record["saved_at"]) + float(record["expires_in"]))
    # The token was validated at login; decoding exp here is only for scheduling.
    try:
        part = record["access_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        candidates.append(float(claims["exp"]))
    except (KeyError, IndexError, ValueError, TypeError):
        pass
    if not candidates:
        raise OAuthRefreshError("OAuth credentials have no valid expiry metadata; sign in again.")
    return min(candidates)


def _save_record(path, record):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".oauth-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(record, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def get_access_token(base_url=None, failed_token=None):
    """Return a current token, or preserve normal API-key behavior if unconfigured.

    failed_token forces renewal only if another process hasn't already replaced it.
    """
    location = os.getenv("OPENAI_OAUTH_CREDENTIALS")
    if not location:
        return os.getenv("OPENAI_API_KEY")
    endpoint = base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    if endpoint.rstrip("/") != "https://api.openai.com/v1":
        raise OAuthRefreshError("ChatGPT plan OAuth requires https://api.openai.com/v1.")
    path = Path(location).expanduser()
    try:
        with _credential_lock(path):
            record = json.loads(path.read_text(encoding="utf-8"))
            token = record.get("access_token")
            if not token:
                raise OAuthRefreshError("OAuth credential file has no access token.")
            force = failed_token is not None and failed_token == token
            if not force and _expires_at(record) > time.time() + 60:
                return token
            if not record.get("refresh_token") or not record.get("client_id"):
                raise OAuthRefreshError("OAuth renewal credentials are missing; sign in again.")
            earliest = record.get("earliest_refresh_at")
            if earliest is not None and float(earliest) > time.time():
                if not force and _expires_at(record) > time.time():
                    return token
                raise OAuthRefreshError("OAuth refresh is not yet allowed; retry after earliest_refresh_at.")
            request = Request(TOKEN_URL, data=urlencode({
                "grant_type": "refresh_token", "client_id": record["client_id"],
                "refresh_token": record["refresh_token"], "resource": "https://api.openai.com/v1",
            }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urlopen(request, timeout=30) as response:
                    replacement = json.load(response)
            except HTTPError as error:
                # Response bodies can contain sensitive material; don't log them.
                status = error.code
                error.close()
                if status in (400, 401, 403):
                    raise OAuthRefreshError(f"OAuth refresh rejected (HTTP {status}); sign in again.") from None
                raise OAuthRefreshError(f"OAuth refresh failed (HTTP {status}); retry later.") from None
            except (URLError, TimeoutError):
                raise OAuthRefreshError("OAuth refresh network failure; retry later.") from None
            if not replacement.get("access_token") or not replacement.get("refresh_token") or not replacement.get("expires_in"):
                raise OAuthRefreshError("OAuth refresh returned incomplete credentials.")
            granted = replacement.get("scope")
            if granted is not None and "chatgpt.tokens.use.direct" not in granted.split():
                raise OAuthRefreshError("OAuth refresh did not grant ChatGPT plan usage; sign in again.")
            updated = dict(record, **replacement)
            # Never retain an old refresh threshold from the previous token.
            updated.pop("earliest_refresh_at", None)
            if replacement.get("earliest_refresh_at") is not None:
                updated["earliest_refresh_at"] = replacement["earliest_refresh_at"]
            updated["saved_at"] = time.time()
            if granted is not None:
                updated["scopes"] = granted.split()
            _save_record(path, updated)
            return updated["access_token"]
    except (OSError, ValueError, TypeError):
        raise OAuthRefreshError("Could not read or save OAuth credentials; check the credential file.") from None


def is_token_expired(error):
    if getattr(error, "status_code", None) != 401:
        return False
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        details = body.get("error", body)
        if isinstance(details, dict) and details.get("code") == "token_expired":
            return True
    return getattr(error, "code", None) == "token_expired" or "token_expired" in str(error)
