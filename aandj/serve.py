"""Production entry point: serves the app with Waitress and runs the reminder / alert scheduler.

Meant to sit behind Cloudflare Tunnel (see deploy/cloudflare-tunnel.md). Listens on 127.0.0.1 only, so the site is
reachable from outside solely through the tunnel.

    python serve.py            # http://127.0.0.1:8000
"""
import os

os.environ.setdefault("AANDJ_BEHIND_HTTPS", "1")

from waitress import serve  # noqa: E402

import app as aandj  # noqa: E402

if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    if os.environ.get("AANDJ_APP_URL"):  # public address used in e-mail / inbox links
        c = aandj.connect()
        c.execute("UPDATE settings SET value=? WHERE key='app_url'", (os.environ["AANDJ_APP_URL"].rstrip("/"),))
        c.commit()
        c.close()
    aandj.start_scheduler()
    print(f"AANDJ reporting running on http://{host}:{port} (Ctrl+C to stop)")
    serve(aandj.app, host=host, port=port, threads=8)
