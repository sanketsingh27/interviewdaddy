import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]


def write_pdf(path: Path, text: str | None) -> None:
    document = canvas.Canvas(str(path))
    if text:
        document.drawString(72, 720, text)
    document.save()


@pytest.fixture(scope="module")
def browser_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("resume-preparation")
    database = directory / "preparations.sqlite3"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    environment = os.environ.copy()
    environment["INTERVIEWDADDY_DATABASE"] = str(database)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                import urllib.request

                urllib.request.urlopen(base_url, timeout=0.25)
                break
            except Exception:
                if server.poll() is not None:
                    pytest.fail("FastAPI server exited before becoming ready")
                time.sleep(0.1)
        else:
            pytest.fail("FastAPI server did not become ready")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=playwright.chromium.executable_path,
            )
            page = browser.new_page()
            yield page, base_url, directory
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_candidate_can_correct_save_and_reopen_preparation(browser_app):
    page, base_url, directory = browser_app
    resume = directory / "resume.pdf"
    write_pdf(resume, "Built a dependable payment service used by 20,000 customers.")

    page.goto(base_url)
    page.get_by_label("Resume PDF").set_input_files(resume)
    page.get_by_role("textbox", name="Extracted resume text").wait_for()
    extracted = page.get_by_role("textbox", name="Extracted resume text")
    assert "20,000 customers" in extracted.input_value()

    corrected_resume = "Built a resilient payment service used by 20,000 customers. I led the API migration."
    extracted.fill(corrected_resume)
    page.get_by_label("Target role").fill("Backend Engineer")
    page.get_by_label("Experience level").select_option(label="Mid-level")
    page.get_by_label("Job description (optional)").fill("Own APIs and payment reliability.")
    page.get_by_role("button", name="Save preparation").click()
    page.get_by_role("status").get_by_text("Preparation saved").wait_for()

    page.get_by_role("button", name="Open preparation").click()
    page.get_by_role("status").get_by_text("Saved preparation opened").wait_for()
    assert page.get_by_role("textbox", name="Extracted resume text").input_value() == corrected_resume
    assert page.get_by_label("Target role").input_value() == "Backend Engineer"
    assert page.get_by_label("Experience level").input_value() == "mid-level"
    assert page.get_by_label("Job description (optional)").input_value() == "Own APIs and payment reliability."

    corrected_after_reopen = f"{corrected_resume} I also documented the migration rollback plan."
    extracted.fill(corrected_after_reopen)
    page.get_by_role("button", name="Save preparation").click()
    page.get_by_role("status").get_by_text("Preparation saved").wait_for()
    assert len(page.request.get(f"{base_url}/api/preparations").json()) == 1
    page.reload()
    page.get_by_role("button", name="Open preparation").click()
    page.get_by_role("status").get_by_text("Saved preparation opened").wait_for()
    assert page.get_by_role("textbox", name="Extracted resume text").input_value() == corrected_after_reopen

    response = page.request.get(f"{base_url}/api/preparations")
    assert response.status == 200
    assert len(response.json()) == 1

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete preparation").click()
    page.get_by_role("status").get_by_text("Preparation deleted from this device").wait_for()
    assert page.request.get(f"{base_url}/api/preparations").json() == []


def test_invalid_and_unreadable_pdfs_show_actionable_errors(browser_app):
    page, base_url, directory = browser_app
    page.goto(base_url)

    invalid_type = directory / "resume.txt"
    invalid_type.write_text("not a PDF")
    page.get_by_label("Resume PDF").set_input_files(invalid_type)
    assert "Choose a PDF" in page.get_by_role("alert").inner_text()

    unreadable_pdf = directory / "unreadable.pdf"
    unreadable_pdf.write_bytes(b"%PDF-1.4\nthis is not a readable PDF")
    page.get_by_label("Resume PDF").set_input_files(unreadable_pdf)
    assert "could not read" in page.get_by_role("alert").inner_text().lower()

    image_only = directory / "image-only.pdf"
    write_pdf(image_only, None)
    page.get_by_label("Resume PDF").set_input_files(image_only)
    message = page.get_by_role("alert").inner_text().lower()
    assert "no readable text" in message
    assert "ocr" in message or "text-based pdf" in message


def test_keyboard_flow_has_named_controls_visible_focus_and_announced_status(browser_app):
    page, base_url, directory = browser_app
    page.goto(base_url)

    assert page.get_by_role("heading", level=1, name="Prepare for your interview").count() == 1
    assert page.get_by_text("Your resume and job description stay in this local app until you delete them.").count() == 1
    assert page.get_by_text("No AI provider is used during resume preparation.").count() == 1

    page.keyboard.press("Tab")
    focused = page.locator(":focus")
    assert focused.count() == 1
    assert focused.evaluate("element => getComputedStyle(element).outlineStyle") != "none"
    page.keyboard.press("Tab")
    assert page.locator(":focus").count() == 1

    assert page.get_by_label("Resume PDF").count() == 1
    assert page.get_by_label("Target role").count() == 1
    assert page.get_by_label("Experience level").count() == 1
    assert page.get_by_label("Job description (optional)").count() == 1
    assert page.get_by_role("status").count() == 1

    unsupported_file = directory / "notes.txt"
    unsupported_file.write_text("not a PDF")
    page.get_by_label("Resume PDF").set_input_files(unsupported_file)
    alert = page.get_by_role("alert")
    assert alert.is_visible()
    assert "Choose a PDF" in alert.inner_text()
