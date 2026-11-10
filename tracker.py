#!/usr/bin/env python3
"""Editorial Manager 투고 상태 감시: 원고 상태가 바뀌면 Slack으로 알린다.

헤드리스 Chrome으로 Author Login → 저자 메뉴의 각 폴더(Submissions Being Processed 등)를 열어
원고 목록(번호·제목·Status Date·Current Status)을 읽고, 직전 스냅샷(state.json)과 비교한다.
Current Status나 Status Date가 바뀐 원고만 알린다. 알림은 한국어나 영어로 보낸다(NOTIFY_LANG).
설정은 환경변수(GitHub Actions에서는 Secrets·Variables)나 config.env에서 읽고, 환경변수가 우선한다.

  python3 tracker.py               # 1회 확인 (GitHub Actions·cron용)
  python3 tracker.py --dry-run     # 알림 없이 결과만 출력, state.json도 갱신 안 함
  python3 tracker.py --debug       # 단계별 HTML/스크린샷을 debug/ 에 저장
  python3 tracker.py --test-slack  # Slack 발송만 시험

설정값
  EM_SITE                       저널 EM 주소 (예: https://www.editorialmanager.com/abcd/) 또는 저널 코드(abcd)
  EM_USERNAME, EM_PASSWORD      그 저널 EM의 저자 계정
  SLACK_WEBHOOK_URL             Slack Incoming Webhook 주소
  SLACK_RELAY_URL, SLACK_RELAY_KEY  연구실 알림 중계 주소와 내 개인 키 (받았다면 웹훅 대신 이것만)
  SLACK_BOT_TOKEN, SLACK_CHANNEL  웹훅 대신 Slack 봇으로 보낼 때 (선택)
  SLACK_MENTION                 알림 앞에 붙일 멘션 (선택, 예: <!channel>, 중계에는 쓰지 않음)
  JOURNAL_NAME                  알림에 표시할 저널 이름 (선택)
  NOTIFY_LANG                   알림과 실행 기록의 언어: ko(기본) 또는 en. 중계는 두 언어를 다 보내고 받는 쪽이 고른다
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
CONFIG_F, STATE_F, LOCK_F = BASE / "config.env", BASE / "state.json", BASE / ".lock"
DEBUG_DIR = BASE / "debug"
CONFIG_KEYS = ("EM_SITE", "EM_USERNAME", "EM_PASSWORD", "SLACK_WEBHOOK_URL", "SLACK_RELAY_URL", "SLACK_RELAY_KEY",
               "SLACK_BOT_TOKEN", "SLACK_CHANNEL", "SLACK_MENTION", "JOURNAL_NAME", "NOTIFY_LANG")
# 처음 만든 서버판과 같은 봇 자격증명 파일: 설정에 Slack 값이 없을 때만 쓴다
LEGACY_TOKEN_F, LEGACY_CHAN_F = Path.home() / ".av_slack_bot_token", Path.home() / ".av_slack_dm_channel"
FAIL_ALERT_AFTER = 3  # 연속 실패가 이 횟수에 도달하면 한 번 알린다
LOGIN_ERR_RE = re.compile(r"does not match any records|incorrect|invalid (user|pass)|account (is )?locked", re.I)
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
LOCAL_TEST = os.environ.get("EM_TRACKER_TEST") == "1"  # 로컬 모의 사이트로 시험할 때만 http://127.0.0.1 허용
SLACK_API = (os.environ.get("EM_TRACKER_SLACK_API") if LOCAL_TEST else None) or "https://slack.com/api"
PREFIX = {"ko": "[EM 감시]", "en": "[EM Watch]"}  # 알림 제목 머리말 (중계는 받는 쪽에서 붙인다)
MAX_SUBJECT, MAX_BODY = 150, 3900

ARGS = None
CFG: dict = {}
SITE = ""
UI_LANG = "ko"


class AuthError(RuntimeError):
    """사이트가 아이디/비밀번호를 거부함 — 계정 잠금을 피하려고 설정이 바뀔 때까지 재시도하지 않는다."""


def tr(ko: str, en: str) -> str:
    """실행 기록·오류 문구를 NOTIFY_LANG 언어로 고른다."""
    return en if UI_LANG == "en" else ko


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_config() -> dict:
    cfg = {}
    if CONFIG_F.exists():
        for line in CONFIG_F.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in CONFIG_KEYS:  # 환경변수(GitHub Secrets)가 config.env보다 우선
        if os.environ.get(k, "").strip():
            cfg[k] = os.environ[k].strip()
    return cfg


def require(cfg: dict, keys: list[str]) -> None:
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        where = "GitHub Secrets" if IN_ACTIONS else "config.env"
        sys.exit(tr(f"{where}에 값이 비어 있습니다: ", f"Missing values in {where}: ") + ", ".join(missing))


def site_url(raw: str) -> str:
    """저널 코드(abcd)나 EM 주소를 'https://…/코드/' 꼴로 맞춘다. EM 주소가 아니면 멈춘다."""
    raw = raw.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return f"https://www.editorialmanager.com/{raw.lower()}/"
    u = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    local = LOCAL_TEST and host in ("127.0.0.1", "localhost")
    if not parts or not (local or host == "editorialmanager.com" or host.endswith(".editorialmanager.com")):
        sys.exit(tr(f"EM_SITE가 Editorial Manager 저널 주소가 아닙니다: {raw}",
                    f"EM_SITE is not an Editorial Manager journal address: {raw}"))
    return f"{u.scheme if local else 'https'}://{u.netloc}/{parts[0]}/"


def gh_output(key: str, value: str) -> None:
    """GitHub Actions의 다음 단계에 값을 넘긴다 (로컬에서는 아무것도 하지 않음)."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


# ---------------------------------------------------------------- Slack 발송
RELAY_WHY = {400: ("보낸 형식이 맞지 않습니다", "the relay rejected the request format"),
             401: ("SLACK_RELAY_KEY가 맞지 않습니다", "SLACK_RELAY_KEY is not valid"),
             403: ("회수된 키입니다. 관리자에게 새 키를 받으세요", "this key has been revoked; ask your admin for a new one"),
             413: ("알림이 너무 깁니다", "the alert is too large"),
             429: ("오늘 보낼 수 있는 알림 수를 넘었습니다", "today's alert limit has been reached"),
             502: ("중계 서버가 Slack에 전달하지 못했습니다", "the relay could not deliver the message to Slack"),
             503: ("중계 서버가 아직 준비되지 않았습니다. 관리자에게 알려 주세요", "the relay is not set up yet; please tell your admin")}


def esc(s: str) -> str:
    """Slack 글에서 특수한 뜻이 있는 &, <, > 를 글자 그대로 보이게 바꾼다."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def send_slack(msgs: dict) -> None:
    """msgs = {"ko": (제목, 본문), "en": (제목, 본문)}. 제목에는 머리말을 붙이지 않은 채로 받는다."""
    relay, key = CFG.get("SLACK_RELAY_URL"), CFG.get("SLACK_RELAY_KEY")
    if relay or key:  # 연구실 중계: 받는 사람은 키가 정하고, 언어·머리말·이스케이프는 중계가 맡는다
        if not (relay and key):
            raise RuntimeError(tr("SLACK_RELAY_URL과 SLACK_RELAY_KEY를 둘 다 넣어야 합니다",
                                  "Set both SLACK_RELAY_URL and SLACK_RELAY_KEY"))
        if not (relay.startswith("https://") or (LOCAL_TEST and relay.startswith("http://127.0.0.1"))):
            raise RuntimeError(tr("SLACK_RELAY_URL은 https:// 로 시작해야 합니다", "SLACK_RELAY_URL must start with https://"))
        subject, body = msgs[UI_LANG]
        payload = {"subject": subject, "body": body, **{lang: {"subject": s, "body": b} for lang, (s, b) in msgs.items()}}
        code, raw = post_json(relay, payload, {"Authorization": f"Bearer {key}"})
        try:
            res = json.loads(raw.decode() or "{}")
        except ValueError:
            res = {}
        if not isinstance(res, dict):
            res = {}
        if code == 200 and res.get("ok") is True:
            return
        why = RELAY_WHY.get(code, ("중계 서버의 응답이 예상과 다릅니다", "unexpected reply from the relay"))
        err = str(res.get("error") or "")[:60]
        raise RuntimeError(tr("알림 중계 실패", "Relay failed") + f" (HTTP {code}{', ' + err if err else ''}): " + tr(*why))

    subject, body = msgs[UI_LANG]
    mention = CFG.get("SLACK_MENTION", "")
    text = (f"{mention} " if mention else "") + f"*{esc(PREFIX[UI_LANG] + ' ' + subject)}*\n{esc(body)}"
    hook = CFG.get("SLACK_WEBHOOK_URL")
    if hook:
        if not (hook.startswith("https://hooks.slack.com/") or (LOCAL_TEST and hook.startswith("http://127.0.0.1"))):
            raise RuntimeError(tr("SLACK_WEBHOOK_URL은 https://hooks.slack.com/ 으로 시작해야 합니다",
                                  "SLACK_WEBHOOK_URL must start with https://hooks.slack.com/"))
        code, raw = post_json(hook, {"text": text, "unfurl_links": False, "unfurl_media": False},
                              {"Content-Type": "application/json; charset=utf-8"})
        res = raw.decode(errors="replace").strip()
        if res != "ok":
            raise RuntimeError(tr("Slack 웹훅 발송 실패", "Slack webhook failed") + f" (HTTP {code}): {res[:200]}")
        return
    token, channel = CFG.get("SLACK_BOT_TOKEN"), CFG.get("SLACK_CHANNEL")
    if not (token and channel) and LEGACY_TOKEN_F.exists() and LEGACY_CHAN_F.exists():
        token, channel = LEGACY_TOKEN_F.read_text().strip(), LEGACY_CHAN_F.read_text().strip()
    if not (token and channel):
        raise RuntimeError(tr("Slack 설정이 없습니다: SLACK_WEBHOOK_URL(또는 SLACK_RELAY_URL과 SLACK_RELAY_KEY)을 넣으세요",
                              "No Slack settings: set SLACK_WEBHOOK_URL (or SLACK_RELAY_URL and SLACK_RELAY_KEY)"))
    data = urllib.parse.urlencode({"channel": channel, "text": text,
                                   "unfurl_links": "false", "unfurl_media": "false"}).encode()
    req = urllib.request.Request(f"{SLACK_API}/chat.postMessage", data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise RuntimeError(tr("Slack 발송 실패", "Slack send failed") + f": {res.get('error')}")


def notify(msgs: dict) -> None:
    """발송에 실패하면 예외가 그대로 올라가 state.json이 갱신되지 않으므로, 다음 실행 때 다시 알린다."""
    subject, body = msgs[UI_LANG]
    if ARGS.dry_run:
        print(f"\n===== [dry-run] {PREFIX[UI_LANG]} {subject} =====\n{body}\n")
        return
    send_slack(msgs)
    log(tr("Slack 발송: ", "Sent to Slack: ") + subject)


# ---------------------------------------------------------------- 브라우저 단계
def dump(page, tag: str) -> None:
    if not ARGS.debug:
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(DEBUG_DIR / f"{tag}.png"), full_page=True)
    for i, fr in enumerate(page.frames):
        try:
            (DEBUG_DIR / f"{tag}.frame{i}.html").write_text(f"<!-- {fr.name} {fr.url} -->\n" + fr.content(), encoding="utf-8")
        except Exception:
            pass


def content_frame(page):
    return page.frame(name="content") or page.main_frame


def clear_overlays(page) -> None:
    """쿠키 동의 배너(OneTrust)가 상위 페이지와 iframe 양쪽에서 클릭을 가로막으므로 모두 제거."""
    for fr in page.frames:
        try:
            fr.evaluate("document.getElementById('onetrust-consent-sdk')?.remove()")
        except Exception:
            pass


def frames_text(page) -> str:
    out = []
    for fr in page.frames:
        try:
            out.append(fr.evaluate("document.body ? document.body.innerText : ''"))
        except Exception:
            pass
    return "\n".join(out)


def login(page, cfg: dict) -> None:
    page.goto(SITE + "default2.aspx", wait_until="networkidle", timeout=60000)
    clear_overlays(page)
    page.click("#Login")
    page.wait_for_function("() => !!document.querySelector('iframe#content')", timeout=30000)
    fr = content_frame(page)
    fr.wait_for_selector("#username", timeout=30000)
    page.wait_for_timeout(1500)
    clear_overlays(page)
    dump(page, "01_login_form")
    fr.fill("#username", cfg["EM_USERNAME"])
    fr.fill("#passwordTextbox", cfg["EM_PASSWORD"])
    fr.click("input[name=authorLogin]")
    # 로그인 후 저자 메뉴 폴더 링크가 보일 때까지 대기 (최대 60초)
    for _ in range(60):
        page.wait_for_timeout(1000)
        clear_overlays(page)
        if find_folders(page):
            dump(page, "02_after_login")
            return
        hint = next((ln.strip() for ln in frames_text(page).splitlines()
                     if LOGIN_ERR_RE.search(ln)), "")
        if hint:
            dump(page, "02_login_failed")
            raise AuthError(hint)
        # 익명화 안내 등 중간 확인 창이 있으면 진행
        for f in page.frames:
            try:
                btn = f.locator("#btnProceedAnonymize:visible")
                if btn.count():
                    btn.first.click()
            except Exception:
                pass
    dump(page, "02_login_failed")
    raise RuntimeError("The author menu did not appear within 60 s after login (the site layout may have changed)")


FOLDERS_JS = r"""
() => [...document.querySelectorAll('[cssclass="main_menu_item_2"]')].flatMap(e => {
  const cnt = e.nextElementSibling;
  const m = cnt && cnt.classList.contains('count') && cnt.innerText.match(/\((\d+)\)/);
  return m ? [{name: e.innerText.replace(/\s+/g, ' ').trim(), count: +m[1], href: e.href || ''}] : [];
})
"""


def find_folders(page) -> list[dict]:
    """Author Main Menu의 폴더 목록: 이름 뒤에 <span class="count">(N)</span>이 붙고, N>0인 폴더만 링크다."""
    for fr in page.frames:
        try:
            found = fr.evaluate(FOLDERS_JS)
        except Exception:
            continue
        if found:
            return found
    return []


EXTRACT_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  for (const t of document.querySelectorAll('table')) {
    const rows = [...t.rows];
    const hi = rows.findIndex(r => /current status|status date|manuscript number/i.test(r.innerText));
    if (hi < 0) continue;
    // 바깥 레이아웃 테이블은 건너뛰고 실제 데이터 테이블만
    if ([...t.querySelectorAll('table')].some(n => /current status|status date/i.test(n.innerText))) continue;
    const hdr = [...rows[hi].cells].map(c => norm(c.innerText));
    for (const r of rows.slice(hi + 1)) {
      const cells = [...r.cells].map(c => norm(c.innerText));
      if (cells.length !== hdr.length || cells.every(c => !c)) continue;
      const o = {};
      hdr.forEach((h, i) => { if (h && !/^action/i.test(h)) o[h] = cells[i]; });
      out.push(o);
    }
  }
  return {rows: out, text: norm(document.body ? document.body.innerText : '')};
}
"""


def read_folder(page, folder: dict, tag: str) -> list[dict]:
    content_frame(page).goto(folder["href"], wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1000)
    clear_overlays(page)
    dump(page, tag)
    best = None
    for f in page.frames:
        try:
            res = f.evaluate(EXTRACT_JS)
        except Exception:
            continue
        if res["rows"]:
            return res["rows"]
        if best is None or len(res["text"]) > len(best["text"]):
            best = res
    # 표 파싱 실패 시 페이지 본문 전체를 하나의 레코드로 남겨 변화만이라도 감지
    return [{"_raw": (best or {}).get("text", "")[:4000]}]


def pick(rec: dict, pattern: str) -> str:
    for k, v in rec.items():
        if re.search(pattern, k, re.I):
            return v
    return ""


def launch(p):
    """설치된 Chrome을 먼저 쓰고, 없으면 Playwright 내장 Chromium을 쓴다."""
    try:
        return p.chromium.launch(headless=True, channel="chrome")
    except Exception:
        return p.chromium.launch(headless=True)


def scrape(cfg: dict) -> dict:
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.set_default_timeout(60000)
        try:
            login(page, cfg)
            folders = find_folders(page)
            items = {}
            for n, folder in enumerate(folders):
                if folder["count"] == 0 or not folder["href"]:
                    continue
                name = folder["name"]
                for rec in read_folder(page, folder, f"03_folder{n}"):
                    num = pick(rec, r"manuscript number")
                    title = pick(rec, r"^title|article title")
                    key = num or title or f"{name}#raw"
                    items[key] = {"folder": name, "number": num, "title": title,
                                  "status": pick(rec, r"current status"), "status_date": pick(rec, r"status date"),
                                  "fields": rec}
            try:
                page.locator("a:text-matches('^\\s*logout\\s*$', 'i')").first.click(timeout=5000)
            except Exception:
                pass
            return {"folders": {f["name"]: f["count"] for f in folders}, "items": items}
        except Exception:
            dump(page, "99_error")
            raise
        finally:
            browser.close()


# ---------------------------------------------------------------- 비교
def diff(old: dict, new: dict) -> list[dict]:
    """알릴 변화만 고른다: Current Status나 Status Date가 바뀐 원고, 새로 보이는 원고, 목록에서 사라진 원고.
    폴더만 옮겨 가거나 다른 칸만 바뀐 것은 알리지 않는다."""
    o, n = old.get("items", {}), new["items"]
    out = []
    for k, it in n.items():
        prev = o.get(k)
        if prev is None:
            out.append({"kind": "new", "item": it})
        elif "_raw" in it["fields"] or "_raw" in prev.get("fields", {}):
            if prev.get("fields") != it["fields"]:
                out.append({"kind": "raw", "item": it})
        elif (prev.get("status"), prev.get("status_date")) != (it["status"], it["status_date"]):
            out.append({"kind": "changed", "item": it, "prev": prev})
    out += [{"kind": "gone", "item": it} for k, it in o.items() if k not in n]
    return out


# ---------------------------------------------------------------- 알림 글 (한국어·영어)
def by_lang(lang: str):
    return lambda ko, en: en if lang == "en" else ko


def both(fn, **kw) -> dict:
    """같은 알림을 두 언어로 만든다: {"ko": (제목, 본문), "en": (제목, 본문)}."""
    out = {}
    for lang in ("ko", "en"):
        s, b = fn(lang, **kw)
        out[lang] = (s[:MAX_SUBJECT], b if len(b) <= MAX_BODY else b[:MAX_BODY - 2] + "\n…")
    return out


def head(it: dict) -> str:
    return " ".join(x for x in [it.get("number"), it.get("title")] if x) or it.get("folder", "")


def item_text(lang: str, it: dict, prev: dict | None = None) -> str:
    """원고 한 편: 번호·제목 줄, Current Status 줄, Status Date 줄. prev가 있으면 바뀐 값에 화살표."""
    t = by_lang(lang)
    if "_raw" in it["fields"]:
        return f"[{it['folder']}] " + t("상태 표를 읽지 못했습니다. EM에서 직접 확인해 보세요.",
                                       "Could not read the status table. Please check EM directly.")
    lines = [head(it)]
    for f, label in (("status", "Current Status"), ("status_date", "Status Date")):
        new = it.get(f) or "-"
        old = (prev or {}).get(f) or "-"
        lines.append(f"{label}: {old} → {new}" if prev is not None and old != new else f"{label}: {new}")
    return "\n".join(lines)


def change_text(lang: str, c: dict) -> str:
    t = by_lang(lang)
    it = c["item"]
    if c["kind"] == "gone":
        last = f"{it.get('status') or '-'} ({it.get('status_date') or '-'})"
        return f"{head(it)}\n" + t(
            f"목록에서 사라졌습니다(마지막 상태: {last}). 공저자 계정이면 교신저자의 조치가 필요한 결정"
            "(수정 요청 등)이 나서 숨겨졌을 수 있습니다. 교신저자의 메일이나 EM에서 확인해 보세요.",
            f"No longer listed (last status: {last}). On a co-author account, a decision that needs the "
            "corresponding author's action (such as a revision request) can hide the manuscript. "
            "Check the corresponding author's email or EM.")
    if c["kind"] == "raw":
        return f"[{it['folder']}] " + t("상태 표를 읽지 못했지만 페이지 내용이 바뀌었습니다. EM에서 확인해 보세요.",
                                       "Could not read the status table, but the page changed. Please check EM.")
    text = item_text(lang, it, c.get("prev"))
    return t("새 원고: ", "New: ") + text if c["kind"] == "new" else text


def m_change(lang: str, changes: list[dict]) -> tuple[str, str]:
    t = by_lang(lang)
    if len(changes) == 1:
        kind, st = changes[0]["kind"], changes[0]["item"].get("status")
        if kind == "gone":
            subject = t("원고가 목록에서 사라졌습니다", "A manuscript is no longer listed")
        elif kind == "new":
            subject = t(f"새 원고: {st}", f"New manuscript: {st}") if st else t("새 원고", "New manuscript")
        else:
            subject = t(f"논문 상태 변경: {st}", f"Status changed: {st}") if st else t("논문 상태 변경", "Status changed")
    else:
        subject = t(f"논문 상태 변경 {len(changes)}건", f"{len(changes)} status changes")
    return subject, "\n\n".join(change_text(lang, c) for c in changes) + f"\n\n{SITE}default2.aspx"


def m_start(lang: str, journal: str, snap: dict) -> tuple[str, str]:
    t = by_lang(lang)
    items = "\n\n".join(item_text(lang, it) for it in snap["items"].values()) \
        or t("지금 보이는 원고가 없습니다.", "No manuscripts are listed right now.")
    return (t(f"{journal} 투고 상태 추적을 시작합니다", f"Now tracking your {journal} submissions"),
            t("앞으로 Current Status나 Status Date가 바뀐 원고만 알려 드립니다.",
              "From now on, you will be alerted only when a manuscript's Current Status or Status Date changes.")
            + f"\n\n{items}\n\n{SITE}default2.aspx")


def m_auth(lang: str, hint: str) -> tuple[str, str]:
    t = by_lang(lang)
    if IN_ACTIONS:  # 저장소에 비밀번호 해시를 남기지 않고, 워크플로가 스스로 꺼져 재시도를 막는다
        how = t("계정 잠금을 막기 위해 이 GitHub Actions 워크플로를 껐습니다.\n"
                "Secrets의 EM_USERNAME/EM_PASSWORD를 고친 뒤 Actions 탭에서 워크플로를 다시 켜세요(Enable workflow).",
                "To avoid locking your account, this GitHub Actions workflow has been turned off.\n"
                "Fix EM_USERNAME/EM_PASSWORD in Secrets, then turn the workflow back on in the Actions tab (Enable workflow).")
    else:
        how = t(f"계정 잠금을 막기 위해 config.env의 EM_USERNAME/EM_PASSWORD가 바뀔 때까지 확인을 멈춥니다.\n설정 파일: {CONFIG_F}",
                f"To avoid locking your account, checks are paused until EM_USERNAME/EM_PASSWORD in config.env change.\n"
                f"Config file: {CONFIG_F}")
    return (t("Editorial Manager 로그인이 거부되었습니다", "Editorial Manager rejected the login"),
            t("EM 화면의 안내: ", "Message from EM: ") + f"{hint}\n\n{how}")


def m_failing(lang: str, err: str) -> tuple[str, str]:
    t = by_lang(lang)
    where = t("GitHub Actions 실행 기록을 보세요.", "See the GitHub Actions run log.") if IN_ACTIONS \
        else t("기록: ", "Log: ") + str(BASE / "tracker.log")
    return (t("상태 확인이 계속 실패합니다", "Status checks keep failing"),
            t(f"{FAIL_ALERT_AFTER}회 연속으로 Editorial Manager 확인에 실패했습니다. 사이트 구조가 바뀌었거나 네트워크 문제일 수 있습니다.",
              f"Checking Editorial Manager failed {FAIL_ALERT_AFTER} times in a row. "
              "The site layout may have changed, or there may be a network problem.")
            + "\n\n" + t("마지막 오류: ", "Last error: ") + f"{err}\n{where}")


def m_recovered(lang: str) -> tuple[str, str]:
    t = by_lang(lang)
    return (t("상태 확인이 다시 정상 동작합니다", "Status checks are working again"),
            t("앞으로 상태가 바뀐 원고가 있으면 다시 알려 드립니다.", "You will be alerted again when a manuscript's status changes."))


def m_test(lang: str) -> tuple[str, str]:
    t = by_lang(lang)
    return t("테스트", "Test"), t("Editorial Manager 상태 알림이 제대로 설정되었습니다.",
                                "Editorial Manager status alerts are set up correctly.")


# ---------------------------------------------------------------- 실행
def main() -> None:
    global ARGS, CFG, SITE, UI_LANG
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--test-slack", action="store_true")
    ARGS = ap.parse_args()

    CFG = cfg = load_config()
    UI_LANG = "en" if cfg.get("NOTIFY_LANG", "").lower().startswith("en") else "ko"

    lock = open(LOCK_F, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(tr("이전 실행이 아직 진행 중이라 건너뜀", "Skipped: the previous run is still in progress"))
        return

    if ARGS.test_slack:
        send_slack(both(m_test))
        log(tr("시험 메시지를 보냈습니다", "Test message sent"))
        return
    if IN_ACTIONS and not any(cfg.get(k) for k in ("EM_SITE", "EM_USERNAME", "EM_PASSWORD")):
        log(tr("Secrets(EM_SITE, EM_USERNAME, EM_PASSWORD)가 아직 없어 건너뜀",
               "Skipped: the Secrets EM_SITE, EM_USERNAME and EM_PASSWORD are not set yet"))
        return
    require(cfg, ["EM_SITE", "EM_USERNAME", "EM_PASSWORD"])
    SITE = site_url(cfg["EM_SITE"])
    journal = cfg.get("JOURNAL_NAME") or SITE.rstrip("/").rsplit("/", 1)[-1]

    state = json.loads(STATE_F.read_text(encoding="utf-8")) if STATE_F.exists() else {}
    now = f"{datetime.now():%Y-%m-%d %H:%M}"
    cred = hashlib.sha256(f"{cfg['EM_USERNAME']}\0{cfg['EM_PASSWORD']}".encode()).hexdigest()
    if not IN_ACTIONS and state.get("bad_cred") == cred:
        log(tr("이전에 거부된 아이디/비밀번호 그대로라 건너뜀 (config.env 수정 후 재개)",
               "Skipped: this username/password was rejected before (edit config.env to resume)"))
        return
    try:
        snap = scrape(cfg)
    except AuthError as e:
        log(tr("로그인 거부: ", "Login rejected: ") + str(e))
        if IN_ACTIONS:  # 저장소에 비밀번호 해시를 남기지 않고, 워크플로가 스스로 꺼져 재시도를 막는다
            gh_output("auth_error", "true")
        elif not ARGS.dry_run:  # 알림 발송이 실패해도 재시도는 막히도록 먼저 저장
            STATE_F.write_text(json.dumps({**state, "bad_cred": cred}, ensure_ascii=False, indent=2), encoding="utf-8")
        notify(both(m_auth, hint=str(e)))
        sys.exit(1)
    except Exception as e:
        state["fail_count"] = state.get("fail_count", 0) + 1
        log(tr(f"확인 실패 ({state['fail_count']}회 연속): ", f"Check failed ({state['fail_count']} in a row): ") + str(e))
        traceback.print_exc()
        if not ARGS.dry_run:
            STATE_F.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if state["fail_count"] == FAIL_ALERT_AFTER:
            notify(both(m_failing, err=str(e)[:500]))
        sys.exit(1)

    recovered = state.get("fail_count", 0) >= FAIL_ALERT_AFTER
    if "items" not in state:
        notify(both(m_start, journal=journal, snap=snap))
    else:
        changes = diff(state, snap)
        if changes:
            notify(both(m_change, changes=changes))
        else:
            log(tr("변경 없음 | ", "No change | ")
                + " / ".join(f"{it['number'] or it['folder']}: {it['status']}" for it in snap["items"].values()))
        if recovered:
            notify(both(m_recovered))

    if not ARGS.dry_run:
        new_state = {**snap, "fail_count": 0}
        if not IN_ACTIONS:  # Actions에서는 확인 시각을 빼서, 바뀐 것이 없으면 커밋도 생기지 않게 한다
            new_state["checked_at"] = now
        STATE_F.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
