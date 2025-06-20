### gattycord, a discord bot for gatty's girls gays theys etc.
monitoring [gatlin's](https://gatlinmusic.com/) [youtube](https://www.youtube.com/c/gatlinmusic) (reliably) and [instagram](https://www.instagram.com/gatlin/) (sometimes)

#

**getting started**
```bash
git clone https://github.com/naestech/gattycord.git
cd gattycord
```


set repository secrets in [github repository secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions) and `.env`:

    DISCORD_WEBHOOK_URL=
    DISCORD_LOG_WEBHOOK_URL=
    DISCORD_USER_ID=
    YOUTUBE_API_KEY=


*github actions will automatically run this workflow at 08:00 & 20:00 utc*

to manually test:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

#

