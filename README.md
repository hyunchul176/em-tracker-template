# Editorial Manager 투고 상태 Slack 알림

English: [README.en.md](README.en.md)

Editorial Manager(EM)에 투고한 원고의 상태가 바뀌면 Slack으로 알려 줍니다. 예를 들어 Under Review가 Decision in Process로 바뀌는 경우입니다. 알림은 한국어나 영어로 받을 수 있습니다.

- **확인 방식:** GitHub가 2시간마다 대신 확인합니다. 내 컴퓨터를 켜 둘 필요가 없습니다.
- **비밀번호 보관:** 아이디와 비밀번호는 내 저장소의 Secrets에만 들어갑니다. 다른 사람은 볼 수 없습니다.

## 준비물

- GitHub 계정
- 투고한 저널의 EM 저자 계정. EM 계정은 보통 저널마다 따로 있습니다. ORCID로만 로그인해 왔다면, 그 저널 EM 로그인 화면의 **Send Login Details**로 사용자명을 받고 비밀번호를 새로 정하세요.
- 알림을 받을 Slack 워크스페이스

## 설정 (10분쯤)

### 1. 저장소 만들기

이 페이지 위쪽의 **Use this template → Create a new repository**를 누릅니다. 공개 범위는 반드시 **Private**으로 고릅니다. 확인 결과(state.json)에 원고 제목과 상태가 저장되기 때문입니다.

### 2. Slack 웹훅 만들기

연구실에서 알림 중계 주소와 개인 키를 받았다면 이 단계는 건너뛰고, 아래 [연구실 중계로 받기](#연구실-중계로-받기-개인-키)를 따르세요. 같은 워크스페이스의 공용 "투고 알림" 봇 토큰을 받았다면 [같은 Slack 워크스페이스에서 함께 쓰기](#같은-slack-워크스페이스에서-함께-쓰기-웹훅-없이-dm)를 따르세요.

1. https://api.slack.com/apps 에서 **Create New App → From scratch**를 누릅니다. 이름(예: 투고 알림)과 워크스페이스를 고릅니다.
2. 왼쪽 메뉴의 **Incoming Webhooks**에서 스위치를 켭니다.
3. 아래쪽의 **Add New Webhook to Workspace**를 누르고, 알림을 받을 채널을 고른 뒤 허용(Allow)을 누릅니다. 나만 들어 있는 비공개 채널(예: #투고-알림)을 권합니다.
4. 만들어진 주소(`https://hooks.slack.com/services/…`)를 복사합니다. 이 주소를 아는 사람은 그 채널에 글을 쓸 수 있으니 남에게 보이지 마세요.
5. Slack에서 그 채널의 알림 설정을 **All new messages**(모든 새 메시지)로 바꿉니다. 그래야 알림을 놓치지 않습니다.

워크스페이스가 앱 설치를 막아 두었다면 관리자 승인이 필요할 수 있습니다.

### 3. Secrets 넣기

새 저장소에서 **Settings → Secrets and variables → Actions → New repository secret**을 눌러 네 가지를 넣습니다.

| 이름 | 값 |
|---|---|
| `EM_SITE` | 저널 EM 주소. 로그인 화면 주소의 앞부분입니다(예: `https://www.editorialmanager.com/abcd/`). |
| `EM_USERNAME` | EM 사용자명 |
| `EM_PASSWORD` | EM 비밀번호 |
| `SLACK_WEBHOOK_URL` | 2단계에서 복사한 주소 |

같은 화면의 **Variables** 탭에는 원하면 다음 세 가지를 넣을 수 있습니다.

| 이름 | 값 |
|---|---|
| `NOTIFY_LANG` | 알림과 실행 기록의 언어. 영어로 받으려면 `en`(기본은 한국어) |
| `JOURNAL_NAME` | 알림에 표시할 저널 이름 |
| `SLACK_MENTION` | 알림마다 붙일 멘션(예: `<!channel>`). 채널 알림 설정과 관계없이 알림이 울립니다. |

### 4. 시험하기

**Actions** 탭에서 **EM 투고 상태 확인 (EM status check) → Run workflow**를 누르고, mode를 차례로 골라 실행합니다.

1. `test-slack`: Slack에 시험 메시지가 오는지 봅니다.
2. `dry-run`: EM에 로그인해 원고 상태를 읽어 오는지 실행 기록에서 봅니다. 알림을 보내지 않고, 결과도 저장하지 않습니다.
3. `check`: 첫 확인 결과가 Slack으로 옵니다.

이후에는 2시간마다 저절로 확인합니다.

## 알림 종류

- **추적 시작:** 첫 확인 결과. 원고마다 Current Status와 Status Date를 보여 줍니다.
- **상태 변경:** Current Status나 Status Date가 바뀐 원고만, 바뀌기 전과 뒤의 값을 보여 줍니다. 폴더만 옮겨 간 것은 알리지 않습니다.
- **새 원고:** 목록에 새로 보이는 원고(예: 수정본 R1)
- **목록에서 사라짐:** 공저자 계정에서는, 교신저자가 조치해야 하는 결정(수정 요청 등)이 나면 원고가 목록에서 숨겨질 수 있습니다.
- **확인 실패:** 3번 이어서 실패할 때, 그리고 다시 정상이 될 때
- **로그인 거부:** 계정이 잠기지 않도록 워크플로가 스스로 꺼집니다. Secrets를 고친 뒤 Actions 탭에서 이 워크플로를 열고 **Enable workflow**를 누르세요.

## 알아 둘 것

- **비밀번호:** Secrets에 넣은 값은 저장한 뒤 나도 다시 볼 수 없고(고치기만 됨), 실행 기록에도 `***`로 가려집니다. 그래도 EM 비밀번호는 다른 곳에서 쓰지 않는 것으로 정하세요.
- **확인 간격:** 2시간입니다. GitHub가 붐비면 수십 분 늦게 돌 수 있습니다. 간격을 바꾸려면 `.github/workflows/em-tracker.yml`의 `cron` 줄을 고칩니다(예: 4시간마다 `17 */4 * * *`).
- **비용:** GitHub 무료 계정은 비공개 저장소의 실행 비용을 매달 12달러어치까지 무료로 줍니다. 리눅스 기본 실행기로 약 2,000분입니다. 이 알림은 한 번에 1–2분이라 한 달에 대략 360–720분을 씁니다.
- **다른 저널:** 이 코드는 Elsevier의 한 저널 EM에서 쓰던 것을 바탕으로 했습니다. 저널마다 EM 화면이 조금씩 다를 수 있어 `dry-run`이 실패할 수 있습니다. 그럴 때는 mode를 `debug`로 실행하면 단계별 화면이 실행 결과의 Artifacts에 3일 동안 올라갑니다. 로그인한 뒤의 화면이 들어 있으니 남에게 보내지 마세요.
- **여러 원고:** EM 계정에 원고가 여러 개면 모두 추적합니다.

## 연구실 중계로 받기 (개인 키)

연구실에서 알림 중계를 운영하면, 연구실 안내 페이지나 관리자에게서 중계 주소와 내 개인 키를 받습니다(보통 연구실 봇의 DM으로 옵니다). 이 키로는 나에게만 알림을 보낼 수 있습니다. 알림은 연구실 봇의 DM으로 옵니다. 추적기는 한국어와 영어 알림을 함께 보내고, 중계가 받는 사람의 언어로 골라 전합니다.

1. 2단계(웹훅)는 건너뜁니다.
2. 3단계에서 `SLACK_WEBHOOK_URL` 대신 다음 두 가지를 Secrets에 넣습니다.

| 이름 | 값 |
|---|---|
| `SLACK_RELAY_URL` | 받은 중계 주소 |
| `SLACK_RELAY_KEY` | 받은 개인 키 |

3. 4단계의 `test-slack`으로 시험합니다. "SLACK_RELAY_KEY가 맞지 않습니다"나 "회수된 키입니다"가 나오면 관리자에게 키를 확인하세요.

키를 잃어버렸거나 남에게 보였다면 관리자에게 알리세요. 그 키만 끊고 새 키를 받을 수 있습니다.

## 같은 Slack 워크스페이스에서 함께 쓰기 (웹훅 없이 DM)

한 사람이 "투고 알림" 봇을 한 번 만들어 두면, 같은 워크스페이스의 다른 사람은 앱이나 웹훅을 만들지 않아도 됩니다. 알림은 봇과의 DM으로 오므로 채널 알림 설정을 바꾸지 않아도 울립니다.

**봇을 만드는 사람 (한 번만)**

1. https://api.slack.com/apps 에서 **Create New App → From scratch**를 누르고, 이름을 "투고 알림"처럼 정합니다.
2. **OAuth & Permissions**의 Bot Token Scopes에 `chat:write` **하나만** 추가합니다.
3. **App Home**의 Show Tabs에서 **Messages Tab**을 켭니다. 꺼져 있으면 DM 발송이 `messages_tab_disabled` 오류로 실패합니다.
4. **Install to Workspace**를 누른 뒤 **Bot User OAuth Token**(`xoxb-…`)을 복사합니다.
5. 이 토큰은 함께 쓸 사람에게 **개인 DM으로만** 전달합니다. 채널, 메일, 문서에는 올리지 마세요.

**각자**

1. 2단계(웹훅)는 건너뜁니다.
2. 3단계에서 `SLACK_WEBHOOK_URL` 대신 다음 두 가지를 Secrets에 넣습니다.

| 이름 | 값 |
|---|---|
| `SLACK_BOT_TOKEN` | 봇을 만든 사람에게 받은 토큰 |
| `SLACK_CHANNEL` | 내 Slack 멤버 ID. Slack에서 내 프로필을 열고 ⋮(더 보기) → **멤버 ID 복사**를 누르면 `U`로 시작하는 값이 복사됩니다. |

**주의.** 이 토큰을 가진 사람은 누구나 그 봇 이름으로 워크스페이스의 아무에게나 메시지를 보낼 수 있습니다.

- 이 용도로만 쓰는 봇을 따로 만들고, 다른 봇의 토큰은 나누지 마세요. 특히 연구실 비서 봇처럼 DM 기록이나 파일을 읽을 수 있는 봇의 토큰은 절대 나누지 마세요. 그런 봇으로 알림을 받으려면 위의 중계 방식을 씁니다.
- 토큰이 샜거나 함께 쓰던 사람이 빠지면, 앱 설정에서 토큰을 폐기(revoke)하고 다시 설치해 새 토큰을 받습니다. 그다음 모두 Secrets의 토큰을 바꿉니다.

## 내 컴퓨터에서 돌리기 (선택, 맥·리눅스)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # Chrome이 없을 때만
cp config.env.example config.env        # 값을 채운 뒤
chmod 600 config.env
python tracker.py --dry-run
```

잘 되면 cron으로 2시간마다 `python tracker.py`를 실행합니다. Windows에서는 GitHub 방식을 쓰세요.
