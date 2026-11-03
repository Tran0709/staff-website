"""Browser test of the create-account flow: sign up → pending → GM approves → sign in.

Creates the example account documented in the README. Run against a fresh demo DB: python tests/signup.py [base_url]
"""
import os
import sys

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(SHOTS, exist_ok=True)
USER, PW = "example_manager", "Example2026!"

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True).new_page()
    page.goto(BASE + "/login")
    page.click("#create-account")
    page.fill("#name", "Example Manager")
    page.fill("#username", USER)
    page.fill("#email", "example@aandj.example")
    page.select_option("#role", "manager")
    page.select_option("#shop_id", label="Cai Yuan Zi")
    page.fill("#password", PW)
    page.fill("#confirm", "mismatch123")
    page.click("button.big-submit")
    expect(page.locator(".flash.error")).to_contain_text("don't match")
    page.fill("#password", PW)
    page.fill("#confirm", PW)
    page.screenshot(path=os.path.join(SHOTS, "s01_register.png"), full_page=True)
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("Account created")
    print("✓ account created (mismatched password rejected first)")

    page.fill("#username", USER)
    page.fill("#password", PW)
    page.click("button.big-submit")
    expect(page.locator(".flash.error")).to_contain_text("waiting for the GM")
    print("✓ pending account cannot sign in")

    page.fill("#username", "joe")
    page.fill("#password", "aandj123")
    page.click("button.big-submit")
    page.goto(BASE + "/inbox")
    expect(page.locator("body")).to_contain_text("New account request: Example Manager")
    page.goto(BASE + "/admin?tab=users")
    page.locator("tr", has_text=USER).locator("button.approve-user").click()
    expect(page.locator(".flash.ok")).to_contain_text(f"{USER} can now sign in")
    page.click("text=Log out")
    print("✓ GM notified and approves")

    page.fill("#username", USER)
    page.fill("#password", PW)
    page.click("button.big-submit")
    expect(page.locator("h1")).to_contain_text("Cai Yuan Zi")
    assert page.goto(BASE + "/pnl").status == 403
    page.goto(BASE + "/today")
    page.screenshot(path=os.path.join(SHOTS, "s02_example_signed_in.png"), full_page=True)
    print("✓ example account signs in as Cai Yuan Zi manager, own shop only")
    b.close()
