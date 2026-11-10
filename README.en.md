# Editorial Manager submission alerts on Slack

한국어: [README.md](README.md)

Get a Slack message when the status of a manuscript you submitted through Editorial Manager (EM) changes, for example from Under Review to Decision in Process. Alerts can be in English or Korean.

- **How it checks:** GitHub checks for you every 2 hours. Your computer does not need to be on.
- **Where your password lives:** your EM username and password go only into your own repository's Secrets. Nobody else can see them.

## What you need

- A GitHub account
- An EM author account for the journal you submitted to. EM accounts are usually separate for each journal. If you have only ever signed in with ORCID, use **Send Login Details** on that journal's EM login page to get your username, then set a new password.
- A Slack workspace to receive the alerts

## Setup (about 10 minutes)

### 1. Create your repository

Click **Use this template → Create a new repository** at the top of this page. Choose **Private**: the check results (state.json) contain your manuscript titles and statuses.

### 2. Create a Slack webhook

If your lab gave you a relay address and a personal key, skip this step and follow [Receive alerts through your lab's relay](#receive-alerts-through-your-labs-relay). If you were given a shared bot token, follow [Share one bot within a Slack workspace](#share-one-bot-within-a-slack-workspace-dm-no-webhook).

1. At https://api.slack.com/apps, click **Create New App → From scratch**. Give it a name (for example, Submission alerts) and choose the workspace.
2. In the left menu, open **Incoming Webhooks** and switch it on.
3. Click **Add New Webhook to Workspace**, choose the channel for alerts, and click **Allow**. A private channel with only you in it works well.
4. Copy the webhook URL (`https://hooks.slack.com/services/…`). Anyone with this URL can post to that channel, so keep it to yourself.
5. In Slack, set that channel's notifications to **All new messages** so that you do not miss alerts.

If your workspace restricts app installation, an admin may need to approve the app.

### 3. Add Secrets

In your new repository, go to **Settings → Secrets and variables → Actions → New repository secret** and add these four:

| Name | Value |
|---|---|
| `EM_SITE` | The journal's EM address: the first part of the login page URL (for example, `https://www.editorialmanager.com/abcd/`) |
| `EM_USERNAME` | Your EM username |
| `EM_PASSWORD` | Your EM password |
| `SLACK_WEBHOOK_URL` | The URL from step 2 |

On the **Variables** tab of the same page, add `NOTIFY_LANG` with the value `en`. Alerts and run logs are in Korean without it. You can also add:

| Name | Value |
|---|---|
| `JOURNAL_NAME` | The journal name shown in alerts |
| `SLACK_MENTION` | A mention added to every alert (for example, `<!channel>`), so that you are notified whatever the channel settings |

### 4. Test

In the **Actions** tab, open **EM 투고 상태 확인 (EM status check) → Run workflow**, then run these modes in order:

1. `test-slack`: check that a test message arrives in Slack.
2. `dry-run`: check in the run log that it signs in to EM and reads your manuscripts. Nothing is sent or saved.
3. `check`: the first result arrives in Slack.

After that, it checks automatically every 2 hours.

## Alerts you get

- **Tracking started:** the first check, with each manuscript's Current Status and Status Date.
- **Status changed:** only manuscripts whose Current Status or Status Date changed, with the old and new values. A move between folders on its own is not reported.
- **New manuscript:** a manuscript that newly appears in your list (for example, a revised version, R1).
- **No longer listed:** on a co-author account, a manuscript can be hidden when a decision needs the corresponding author's action (such as a revision request).
- **Checks failing:** after 3 failures in a row, and again when checks work again.
- **Login rejected:** the workflow switches itself off so that your account does not get locked. Fix the Secrets, then open this workflow in the Actions tab and click **Enable workflow**.

## Good to know

- **Password:** once saved, a Secret cannot be viewed again, even by you (it can only be replaced), and it shows as `***` in run logs. Even so, use an EM password that you do not use anywhere else.
- **Interval:** every 2 hours. When GitHub is busy, a run can start tens of minutes late. To change the interval, edit the `cron` line in `.github/workflows/em-tracker.yml` (for example, every 4 hours: `17 */4 * * *`).
- **Cost:** free GitHub accounts get USD 12 of Actions usage a month for private repositories, about 2,000 minutes on the standard Linux runner. One check takes 1–2 minutes, so this uses roughly 360–720 minutes a month.
- **Other journals:** this code was first written for one Elsevier journal's EM. EM pages differ a little between journals, so `dry-run` may fail. If it does, run the mode `debug`: screenshots of each step are uploaded to the run's Artifacts for 3 days. They show pages after you sign in, so do not share them.
- **Several manuscripts:** every manuscript in your EM account is tracked.

## Receive alerts through your lab's relay

If your lab runs an alert relay, your admin gives you a relay address and your own personal key (usually by a direct message from the lab's bot). The key can send alerts only to you. Alerts arrive as a direct message from the lab's bot. The tracker sends each alert in both English and Korean, and the relay picks your language.

1. Skip step 2 (webhook).
2. In step 3, add these two Secrets instead of `SLACK_WEBHOOK_URL`:

| Name | Value |
|---|---|
| `SLACK_RELAY_URL` | The relay address you were given |
| `SLACK_RELAY_KEY` | Your personal key |

3. Run `test-slack` from step 4. If you see "SLACK_RELAY_KEY is not valid" or "this key has been revoked", check the key with your admin.

If you lose your key or someone else sees it, tell your admin. They can cancel that key and give you a new one.

## Share one bot within a Slack workspace (DM, no webhook)

Once one person makes a "Submission alerts" bot, others in the same workspace do not need their own app or webhook. Alerts arrive as a direct message from the bot, so they notify you whatever your channel settings.

**The person who makes the bot (once)**

1. At https://api.slack.com/apps, click **Create New App → From scratch** and name it, for example, Submission alerts.
2. Under **OAuth & Permissions**, add **only** `chat:write` to Bot Token Scopes.
3. Under **App Home**, in Show Tabs, switch on **Messages Tab**. Without it, direct messages fail with the error `messages_tab_disabled`.
4. Click **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-…`).
5. Give this token to the people who will use it **by direct message only**. Never post it in a channel, an email or a document.

**Everyone else**

1. Skip step 2 (webhook).
2. In step 3, add these two Secrets instead of `SLACK_WEBHOOK_URL`:

| Name | Value |
|---|---|
| `SLACK_BOT_TOKEN` | The token from the person who made the bot |
| `SLACK_CHANNEL` | Your Slack member ID. Open your profile in Slack, click ⋮ (More) → **Copy member ID**. It starts with `U`. |

**Caution.** Anyone with this token can message anyone in the workspace as that bot.

- Make a bot just for this purpose, and never share another bot's token. Above all, never share the token of a bot that can read direct messages or files, such as a lab assistant bot. To get alerts from a bot like that, use the relay instead.
- If the token leaks, or someone stops using it, revoke the token in the app settings and reinstall the app to get a new one. Then everyone replaces the token in their Secrets.

## Run on your own computer (optional, macOS or Linux)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # only if Chrome is not installed
cp config.env.example config.env        # then fill in the values (add NOTIFY_LANG=en)
chmod 600 config.env
python tracker.py --dry-run
```

If that works, run `python tracker.py` every 2 hours with cron. On Windows, use the GitHub setup.
