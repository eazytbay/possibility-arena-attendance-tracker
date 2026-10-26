"""SMS providers. Only Bulk SMS Nigeria is implemented; add another class with the same send() to switch."""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

API_URL = "https://www.bulksmsnigeria.com/api/v2/sms"


@dataclass
class SendResult:
    ok: bool
    message_id: str | None = None
    code: str | None = None
    error: str | None = None
    fatal: bool = False  # True means stop the whole run (for example, no credit left)


def to_international(phone: str) -> str:
    """08012345678 -> 2348012345678"""
    return "234" + phone[1:] if phone.startswith("0") else phone


class BulkSmsNigeriaProvider:
    def __init__(self, token: str, sender_id: str, gateway: str = "direct-corporate", timeout: int = 20):
        if not token or not sender_id:
            raise ValueError("SMS token and sender ID are required")
        if len(sender_id) > 11:
            raise ValueError("Sender ID can be at most 11 characters")
        self._token, self._sender, self._gateway, self._timeout = token, sender_id, gateway, timeout

    def send(self, phone: str, text: str) -> SendResult:
        payload = json.dumps({"from": self._sender, "to": to_international(phone), "body": text,
                              "gateway": self._gateway, "unicode": False}).encode()
        req = urllib.request.Request(API_URL, data=payload, method="POST", headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
            "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (fixed https URL)
                body = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read() or b"{}")
            except ValueError:
                body = {}
            code = body.get("code") or f"HTTP-{exc.code}"
            msg = (body.get("error") or {}).get("message") or str(exc)
            return SendResult(False, code=code, error=msg[:200], fatal=exc.code in (401, 402, 403))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return SendResult(False, error=f"network: {exc}"[:200])
        if body.get("status") == "success":
            return SendResult(True, message_id=str((body.get("data") or {}).get("message_id") or ""),
                              code=body.get("code"))
        return SendResult(False, code=body.get("code"), error=str(body.get("message") or "rejected")[:200])


def provider_from_config(cfg) -> BulkSmsNigeriaProvider | None:
    """Return a live provider, or None when SMS is switched off or not configured."""
    if not cfg.get("SMS_ENABLED") or not cfg.get("SMS_API_TOKEN") or not cfg.get("SMS_SENDER_ID"):
        return None
    return BulkSmsNigeriaProvider(cfg["SMS_API_TOKEN"], cfg["SMS_SENDER_ID"], cfg.get("SMS_GATEWAY", "direct-corporate"))
