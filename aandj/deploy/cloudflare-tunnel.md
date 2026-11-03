# Put AANDJ online with Cloudflare Tunnel (free)

The app runs on one always-on Windows computer, such as an office PC or a mini-PC. Cloudflare Tunnel publishes it at your
own address, for example `https://reports.yourdomain.com`, with HTTPS. You don't open router ports, and the PC is never
exposed directly: it only makes an outgoing connection to Cloudflare.

```
phone / laptop ──HTTPS──▶ Cloudflare ──tunnel──▶ cloudflared on the PC ──▶ python serve.py (127.0.0.1:8000)
```

You need a Cloudflare account and a domain on Cloudflare (the free plan is enough). The site is only up while that PC
is on and connected.

> **First, delete the failed Workers/Pages project.** In the Cloudflare dashboard, go to Workers & Pages → your
> `staff-website` project → Settings → Delete. Otherwise every push to GitHub starts another build that fails.
> That build failure is expected: this app can't run on Workers or Pages.

## 1. Prepare the PC (one time)

1. Install Python 3.10+ from python.org and tick "Add Python to PATH".
2. Get the code:
   ```bash
   git clone https://github.com/Tran0709/staff-website.git C:\aandj
   cd C:\aandj
   pip install -r requirements.txt
   ```
   Keep the folder path short (for example `C:\aandj`) to avoid Windows long-path errors.
3. Choose the starting data:
   - **Demo data:** just start it. The demo accounts use password `aandj123`.
   - **Real go-live (empty system):** set these before the first start:
     ```bash
     setx AANDJ_NO_DEMO 1
     setx AANDJ_ADMIN_PASSWORD "a-strong-password"
     ```
     Then open a new terminal so the settings take effect.
4. Test it locally:
   ```bash
   python serve.py
   ```
   Open http://127.0.0.1:8000. Signing in won't work here, which is expected: the session cookie is HTTPS-only, and
   sign-in works once you go through the tunnel. To try sign-in locally, run `python app.py` instead
   (http://127.0.0.1:5000).

## 2. Install cloudflared (one time)

```bash
winget install --id Cloudflare.cloudflared
```

Or download the Windows installer from Cloudflare's "Downloads" page in the Zero Trust docs. Check it installed:
`cloudflared --version`.

### Quick test, no domain needed

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

It prints a temporary `https://….trycloudflare.com` address that works from any phone. Use this for a test only:
the address changes every time.

## 3. Create the permanent tunnel

The simplest way is from the dashboard, with no config files:

1. Cloudflare dashboard → **Zero Trust** → **Networks → Tunnels** → **Create a tunnel** → type **Cloudflared**.
   Name it `aandj`.
2. Choose **Windows**. Copy the command it shows (`cloudflared.exe service install <token>`) and run it in an
   **administrator** terminal. This installs cloudflared as a Windows service, so it starts with the PC.
3. **Public hostname:** subdomain `reports`, your domain, service type **HTTP**, URL `127.0.0.1:8000` → Save.

Your site is now at `https://reports.yourdomain.com`, as long as `serve.py` is running (step 4).

## 4. Start the app automatically

1. Edit `deploy\start_aandj.bat` and change `AANDJ_APP_URL` to your public address. This is used for links in e-mails
   and the inbox.
2. Open **Task Scheduler** → **Create Task…**:
   - **General:** "Run whether user is logged on or not" and "Run with highest privileges".
   - **Triggers:** "At startup".
   - **Actions:** Start a program → `C:\aandj\deploy\start_aandj.bat`.
   - **Settings:** "If the task fails, restart every 1 minute".
3. Right-click the task → **Run**, then open your address on a phone.

Server output goes to `data\server.log`.

## 5. Recommended Cloudflare settings (free)

- **Zero Trust → Access → Applications:** add your hostname and allow only staff e-mail addresses. Cloudflare then
  checks people with a one-time e-mail code before they reach the sign-in page. This is an extra lock on top of the
  app's own passwords and 2FA.
- In the app, as the GM: change every demo password, then Admin → Controls → tick **Require two-factor login**.

## Updating to a new version

```bash
cd C:\aandj
git pull
pip install -r requirements.txt
```

Then restart the task in Task Scheduler (End, then Run). Your data in `data\` is not touched.

## Backups

A copy of the database is saved every day to `data\backups\`. Copy that folder somewhere else regularly, for example
to OneDrive or Google Drive. If the PC's disk fails, those copies are your only backup.
