@echo off
rem Starts the AANDJ reporting server. Used by Windows Task Scheduler at log-on (see deploy\cloudflare-tunnel.md).
cd /d "%~dp0.."
rem Your public address, used in e-mail links. Change to your own domain.
if "%AANDJ_APP_URL%"=="" set AANDJ_APP_URL=https://reports.example.com
python serve.py >> data\server.log 2>&1
