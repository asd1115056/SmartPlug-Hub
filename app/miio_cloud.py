"""Xiaomi cloud token lookup — native HTTP implementation."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from requests.cookies import RequestsCookieJar
from Crypto.Cipher import ARC4

logger = logging.getLogger(__name__)

_EXTRACTOR_SRC = Path(__file__).parent.parent / "vendor" / "xiaomi-extractor" / "token_extractor.py"


def _load_regions() -> tuple[str, ...]:
    m = re.search(r"^SERVERS\s*=\s*\[([^\]]+)\]", _EXTRACTOR_SRC.read_text(), re.MULTILINE)
    if not m:
        return ("cn", "de", "us", "ru", "tw", "sg", "in", "i2")
    return tuple(s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip())


REGIONS = _load_regions()


# ── Session state ─────────────────────────────────────────────────────────────

@dataclass
class _Session:
    http: requests.Session
    agent: str
    username: str
    password: str
    region: str
    mac: str
    sign: str | None = None
    ssecurity: str | None = None
    user_id: str | None = None
    c_user_id: str | None = None
    location: str | None = None
    service_token: str | None = None
    two_fa_context: str | None = None


_sessions: dict[str, _Session] = {}


# ── Crypto helpers ────────────────────────────────────────────────────────────

def _generate_agent() -> str:
    agent_id = "".join(chr(random.randint(65, 69)) for _ in range(13))
    suffix = "".join(chr(random.randint(97, 122)) for _ in range(18))
    return f"{suffix}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"


def _generate_nonce() -> str:
    millis = round(time.time() * 1000)
    raw = os.urandom(8) + (int(millis / 60000)).to_bytes(4, byteorder="big")
    return base64.b64encode(raw).decode()


def _signed_nonce(nonce: str, ssecurity: str) -> str:
    h = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce))
    return base64.b64encode(h.digest()).decode()


def _encrypt_rc4(password: str, payload: str) -> str:
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return base64.b64encode(r.encrypt(payload.encode())).decode()


def _decrypt_rc4(password: str, payload: str) -> bytes:
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return r.encrypt(base64.b64decode(payload))


def _enc_signature(url: str, method: str, signed_nonce: str, params: dict) -> str:
    parts = [method.upper(), url.split("com")[1].replace("/app/", "/")]
    parts += [f"{k}={v}" for k, v in params.items()]
    parts.append(signed_nonce)
    return base64.b64encode(hashlib.sha1("&".join(parts).encode()).digest()).decode()


def _enc_params(url: str, method: str, signed_nonce: str, nonce: str, params: dict, ssecurity: str) -> dict:
    p = dict(params)
    p["rc4_hash__"] = _enc_signature(url, method, signed_nonce, p)
    for k, v in p.items():
        p[k] = _encrypt_rc4(signed_nonce, v)
    p["signature"] = _enc_signature(url, method, signed_nonce, p)
    p["ssecurity"] = ssecurity
    p["_nonce"] = nonce
    return p


def _parse_json(text: str) -> dict:
    return json.loads(text.replace("&&&START&&&", ""))


def _get_cookie(jar: RequestsCookieJar, name: str) -> str | None:
    """Return first matching cookie value; avoids RuntimeError on duplicate names."""
    for c in jar:
        if c.name == name:
            return c.value
    return None


# ── API call ──────────────────────────────────────────────────────────────────

def _api_call(s: _Session, region: str, endpoint: str, data: str) -> dict | None:
    if not s.user_id or not s.service_token or not s.ssecurity:
        logger.error("_api_call: missing credentials user_id=%s service_token=%s ssecurity=%s",
                     bool(s.user_id), bool(s.service_token), bool(s.ssecurity))
        return None
    url = ("https://" + ("" if region == "cn" else f"{region}.") + "api.io.mi.com/app") + endpoint
    nonce = _generate_nonce()
    sn = _signed_nonce(nonce, s.ssecurity)
    fields = _enc_params(url, "POST", sn, nonce, {"data": data}, s.ssecurity)
    headers = {
        "Accept-Encoding": "identity",
        "User-Agent": s.agent,
        "Content-Type": "application/x-www-form-urlencoded",
        "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
        "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
    }
    cookies = {
        "userId": str(s.user_id),
        "yetAnotherServiceToken": str(s.service_token),
        "serviceToken": str(s.service_token),
        "locale": "en_GB",
        "timezone": "GMT+02:00",
        "is_daylight": "1",
        "dst_offset": "3600000",
        "channel": "MI_APP_STORE",
    }
    r = s.http.post(url, headers=headers, cookies=cookies, params=fields)
    if r.status_code == 200:
        return json.loads(_decrypt_rc4(_signed_nonce(fields["_nonce"], s.ssecurity), r.text))
    return None


# ── Login steps ───────────────────────────────────────────────────────────────

def _step1(s: _Session) -> bool:
    logger.debug("step1: GET serviceLogin for %s", s.username)
    headers = {"User-Agent": s.agent, "Content-Type": "application/x-www-form-urlencoded"}
    r = s.http.get(
        "https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true",
        headers=headers, cookies={"userId": s.username},
    )
    logger.debug("step1: status=%s", r.status_code)
    if r.status_code != 200:
        return False
    j = _parse_json(r.text)
    if "_sign" in j:
        s.sign = j["_sign"]
        logger.debug("step1: got _sign")
        return True
    if "ssecurity" in j:
        s.ssecurity, s.user_id, s.c_user_id = j["ssecurity"], j["userId"], j["cUserId"]
        s.location = j["location"]
        logger.debug("step1: already authenticated, got ssecurity")
        return True
    logger.error("step1: unexpected response keys: %s", list(j.keys()))
    return False


def _step2(s: _Session, captcha_code: str | None = None) -> dict:
    """Returns {status: 'ok'|'captcha'|'2fa'|'error', ...}"""
    logger.debug("step2: POST serviceLoginAuth2 (captcha=%s)", captcha_code is not None)
    url = "https://account.xiaomi.com/pass/serviceLoginAuth2"
    headers = {"User-Agent": s.agent, "Content-Type": "application/x-www-form-urlencoded"}
    fields = {
        "sid": "xiaomiio",
        "hash": hashlib.md5(s.password.encode()).hexdigest().upper(),
        "callback": "https://sts.api.io.mi.com/sts",
        "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "user": s.username,
        "_sign": s.sign,
        "_json": "true",
    }
    if captcha_code:
        fields["captCode"] = captcha_code

    r = s.http.post(url, headers=headers, params=fields, allow_redirects=False)
    logger.debug("step2: status=%s", r.status_code)
    if r.status_code != 200:
        return {"status": "error", "msg": f"HTTP {r.status_code}"}

    j = _parse_json(r.text)
    logger.debug("step2: response keys=%s code=%s", list(j.keys()), j.get("code"))

    if "captchaUrl" in j and j["captchaUrl"] is not None:
        logger.info("step2: captcha required")
        img_url = j["captchaUrl"]
        if img_url.startswith("/"):
            img_url = "https://account.xiaomi.com" + img_url
        img_r = s.http.get(img_url)
        if img_r.status_code != 200:
            return {"status": "error", "msg": "Failed to fetch captcha image"}
        return {"status": "captcha", "image_bytes": img_r.content}

    if j.get("code") == 87001:
        logger.info("step2: invalid captcha (code 87001)")
        return {"status": "error", "msg": "Invalid captcha — please try again"}

    if "ssecurity" in j and len(str(j["ssecurity"])) > 4:
        s.ssecurity = j["ssecurity"]
        s.user_id = j.get("userId")
        s.c_user_id = j.get("cUserId")
        s.location = j.get("location")
        logger.debug("step2: authenticated, userId=%s location=%s", s.user_id, s.location)
        return {"status": "ok"}

    if "notificationUrl" in j:
        logger.info("step2: 2FA required")
        return {"status": "2fa", "url": j["notificationUrl"]}

    logger.error("step2: unhandled response: %s", r.text[:300])
    return {"status": "error", "msg": "Login failed — check credentials"}


def _step3(s: _Session) -> bool:
    logger.debug("step3: GET location=%s", s.location)
    r = s.http.get(s.location, headers={"User-Agent": s.agent})
    logger.debug("step3: status=%s", r.status_code)
    if r.status_code == 200:
        s.service_token = _get_cookie(r.cookies, "serviceToken") or _get_cookie(s.http.cookies, "serviceToken")
        logger.debug("step3: serviceToken=%s", bool(s.service_token))
    return r.status_code == 200


def _install_service_token(s: _Session) -> None:
    for d in [".api.io.mi.com", ".io.mi.com", ".mi.com"]:
        s.http.cookies.set("serviceToken", s.service_token, domain=d)
        s.http.cookies.set("yetAnotherServiceToken", s.service_token, domain=d)


# ── 2FA ───────────────────────────────────────────────────────────────────────

def _start_2fa(s: _Session, notification_url: str) -> None:
    logger.debug("2fa: starting flow, notification_url=%s", notification_url)
    headers = {"User-Agent": s.agent, "Content-Type": "application/x-www-form-urlencoded"}
    r = s.http.get(notification_url, headers=headers)
    logger.debug("2fa: authStart status=%s final_url=%s", r.status_code, r.url)
    context = parse_qs(urlparse(notification_url).query)["context"][0]
    s.two_fa_context = context
    r = s.http.get("https://account.xiaomi.com/identity/list",
               params={"sid": "xiaomiio", "context": context, "_locale": "en_US"}, headers=headers)
    logger.debug("2fa: identity/list status=%s", r.status_code)
    r = s.http.post(
        "https://account.xiaomi.com/identity/auth/sendEmailTicket",
        params={"_dc": str(int(time.time() * 1000)), "sid": "xiaomiio",
                "context": context, "mask": "0", "_locale": "en_US"},
        data={"retry": "0", "icode": "", "_json": "true", "ick": _get_cookie(s.http.cookies, "ick") or ""},
        headers=headers,
    )
    logger.debug("2fa: sendEmailTicket status=%s body=%s", r.status_code, r.text[:100])


def _verify_2fa(s: _Session, code: str) -> bool:
    logger.debug("2fa: verifying code (len=%d)", len(code))
    headers = {"User-Agent": s.agent, "Content-Type": "application/x-www-form-urlencoded"}
    context = s.two_fa_context

    r = s.http.post(
        "https://account.xiaomi.com/identity/auth/verifyEmail",
        params={"_flag": "8", "_json": "true", "sid": "xiaomiio",
                "context": context, "mask": "0", "_locale": "en_US"},
        data={"_flag": "8", "ticket": code, "trust": "false",
              "_json": "true", "ick": _get_cookie(s.http.cookies, "ick") or ""},
        headers=headers,
    )
    logger.debug("2fa: verifyEmail status=%s", r.status_code)
    if r.status_code != 200:
        logger.error("2fa: verifyEmail failed status=%s body=%s", r.status_code, r.text[:200])
        return False

    try:
        finish_loc = r.json().get("location")
    except Exception:
        finish_loc = r.headers.get("Location")
        if not finish_loc and r.text:
            m = re.search(r"https://account\.xiaomi\.com/identity/result/check\?[^\"']+", r.text)
            if m:
                finish_loc = m.group(0)

    if not finish_loc:
        r0 = s.http.get("https://account.xiaomi.com/identity/result/check",
                         params={"sid": "xiaomiio", "context": context, "_locale": "en_US"},
                         headers=headers, allow_redirects=False)
        if r0.status_code in (301, 302):
            finish_loc = r0.headers.get("Location")

    logger.debug("2fa: finish_loc=%s", finish_loc)
    if not finish_loc:
        logger.error("2fa: could not determine finish location")
        return False

    if "identity/result/check" in finish_loc:
        r = s.http.get(finish_loc, headers=headers, allow_redirects=False)
        end_url = r.headers.get("Location")
    else:
        end_url = finish_loc

    logger.debug("2fa: end_url=%s", end_url)
    if not end_url:
        logger.error("2fa: no Auth2/end URL found")
        return False

    r = s.http.get(end_url, headers=headers, allow_redirects=False)
    logger.debug("2fa: Auth2/end status=%s", r.status_code)
    if r.status_code == 200 and "Xiaomi Account - Tips" in r.text:
        r = s.http.get(end_url, headers=headers, allow_redirects=False)
        logger.debug("2fa: Auth2/end(retry) status=%s", r.status_code)

    ext_prag = r.headers.get("extension-pragma")
    logger.debug("2fa: extension-pragma=%s", ext_prag)
    if ext_prag:
        try:
            ep = json.loads(ext_prag)
            if ep.get("ssecurity"):
                s.ssecurity = ep["ssecurity"]
        except Exception:
            pass

    if not s.ssecurity:
        logger.error("2fa: no ssecurity in extension-pragma")
        return False

    sts_url = r.headers.get("Location")
    if not sts_url and r.text:
        idx = r.text.find("https://sts.api.io.mi.com/sts")
        if idx != -1:
            end = r.text.find('"', idx)
            sts_url = r.text[idx:end if end != -1 else idx + 300]

    logger.debug("2fa: sts_url=%s", sts_url)
    if not sts_url:
        logger.error("2fa: no STS URL found")
        return False

    # Extract userId from STS URL before it gets consumed by redirect
    if not s.user_id:
        m = re.search(r'[?&]userId=([^&"\']+)', sts_url)
        if m:
            s.user_id = m.group(1)
            logger.debug("2fa: extracted userId=%s from sts_url", s.user_id)

    r = s.http.get(sts_url, headers=headers, allow_redirects=True)
    logger.debug("2fa: STS status=%s final_url=%s", r.status_code, r.url)
    if r.status_code != 200:
        logger.error("2fa: STS failed status=%s", r.status_code)
        return False

    s.service_token = _get_cookie(s.http.cookies, "serviceToken")
    logger.debug("2fa: serviceToken obtained=%s", bool(s.service_token))
    if not s.service_token:
        logger.error("2fa: serviceToken not found in cookies; jar=%s",
                     list(s.http.cookies.keys()))
        return False

    _install_service_token(s)
    if not s.user_id:
        s.user_id = _get_cookie(s.http.cookies, "userId")
    logger.debug("2fa: user_id=%s", s.user_id)
    return True


# ── Device lookup ─────────────────────────────────────────────────────────────

def _find_device(s: _Session, region: str, mac: str) -> tuple[str, str] | None:
    target = mac.upper().replace("-", ":")
    logger.debug("find_device: region=%s target=%s", region, target)

    homes = _api_call(s, region, "/v2/homeroom/gethome",
        '{"fg": true, "fetch_share": true, "fetch_share_dev": true, "limit": 300, "app_ver": 7}')
    home_ids: list[tuple] = []
    if homes:
        for h in homes.get("result", {}).get("homelist", []):
            home_ids.append((h["id"], s.user_id))

    cnt = _api_call(s, region, "/v2/user/get_device_cnt", '{"fetch_own": true, "fetch_share": true}')
    if cnt:
        for h in cnt.get("result", {}).get("share", {}).get("share_family", []):
            home_ids.append((h["home_id"], h["home_owner"]))

    logger.debug("find_device: %d home(s) to search", len(home_ids))
    for home_id, owner_id in home_ids:
        data = f'{{"home_owner": {owner_id}, "home_id": {home_id}, "limit": 200, "get_split_device": true, "support_smart_home": true}}'
        devices = _api_call(s, region, "/v2/home/home_device_list", data)
        if not devices:
            logger.debug("find_device: no response for home %s", home_id)
            continue
        device_list = devices.get("result", {}).get("device_info", []) or []
        logger.debug("find_device: home %s has %d device(s)", home_id, len(device_list))
        for device in device_list:
            if device.get("mac", "").upper().replace("-", ":") == target:
                token, did = device.get("token"), device.get("did")
                if token and did:
                    return token, str(did)
    return None


# ── Public async API ──────────────────────────────────────────────────────────

async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


async def start_login(username: str, password: str, region: str, mac: str) -> dict:
    session_id = uuid.uuid4().hex
    s = _Session(http=requests.Session(), agent=_generate_agent(),
                 username=username, password=password, region=region, mac=mac)
    _sessions[session_id] = s

    if not await _run(_step1, s):
        _sessions.pop(session_id)
        raise RuntimeError("Login failed — invalid username or network error")

    result = await _run(_step2, s, None)
    return await _handle_step2(session_id, s, result)


async def solve_challenge(session_id: str, solution: str) -> dict:
    s = _sessions.get(session_id)
    if not s:
        raise ValueError("Session not found or expired")

    if s.two_fa_context:
        ok = await _run(_verify_2fa, s, solution)
        if not ok:
            _sessions.pop(session_id, None)
            raise RuntimeError("2FA verification failed — check your email code")
        return await _complete_login(session_id, s)
    else:
        result = await _run(_step2, s, solution)
        return await _handle_step2(session_id, s, result)


async def _handle_step2(session_id: str, s: _Session, result: dict) -> dict:
    status = result["status"]

    if status == "captcha":
        return {
            "session_id": session_id,
            "challenge": "captcha",
            "captcha_b64": base64.b64encode(result["image_bytes"]).decode(),
        }

    if status == "2fa":
        await _run(_start_2fa, s, result["url"])
        return {"session_id": session_id, "challenge": "2fa"}

    if status == "error":
        _sessions.pop(session_id, None)
        logger.error("miio-cloud: login error for %s: %s", s.mac, result["msg"])
        raise RuntimeError(result["msg"])

    return await _complete_login(session_id, s)


async def _complete_login(session_id: str, s: _Session) -> dict:
    logger.debug("complete_login: location=%s service_token=%s ssecurity=%s user_id=%s",
                 bool(s.location), bool(s.service_token), bool(s.ssecurity), s.user_id)
    if s.location and not s.service_token:
        if not await _run(_step3, s):
            _sessions.pop(session_id, None)
            raise RuntimeError("Failed to obtain service token")

    if not s.service_token:
        _sessions.pop(session_id, None)
        logger.error("miio-cloud: no service token for %s", s.mac)
        raise RuntimeError("No service token after login")

    found = await _run(_find_device, s, s.region, s.mac)
    _sessions.pop(session_id, None)

    if not found:
        logger.error("miio-cloud: device %s not found in region %s", s.mac, s.region)
        raise ValueError(f"Device {s.mac} not found in region {s.region}")

    token, did = found
    logger.info("miio-cloud: found device %s token=%s", s.mac, token[:8] + "…")
    return {"token": token, "did": did}
