import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class ControlledOpenAIHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.requests.append(request)
        if request["model"] != "gpt-6-luna":
            self.send_error(400, "Unexpected model")
            return
        context = json.loads(request["input"][1]["content"])
        if context["latest_answer"] == "trigger provider failure":
            self.send_error(503)
            return
        if context["latest_answer"] == "slow answer":
            time.sleep(0.3)
        question = (
            "What trade-off did you make in the payment API migration?"
            if context["question_type"] == "relevant follow-up"
            else "Tell me about the payment service you built."
        )
        body = json.dumps({"output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": question, "annotations": []},
            ]},
        ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def browser_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("resume-preparation")
    database = directory / "preparations.sqlite3"
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ControlledOpenAIHandler)
    import threading

    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    environment = os.environ.copy()
    environment.pop("OPENAI_MODEL", None)
    environment["INTERVIEWDADDY_DATABASE"] = str(database)
    environment["OPENAI_API_KEY"] = "controlled-test-key"
    environment["OPENAI_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"
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
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
            )
            page = browser.new_page()
            yield page, base_url, directory
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=5)
        provider.shutdown()
        provider.server_close()


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
    assert page.locator("#status-message").get_attribute("role") == "status"
    assert page.locator("#capture-state").get_attribute("role") == "status"

    unsupported_file = directory / "notes.txt"
    unsupported_file.write_text("not a PDF")
    page.get_by_label("Resume PDF").set_input_files(unsupported_file)
    alert = page.get_by_role("alert")
    assert alert.is_visible()
    assert "Choose a PDF" in alert.inner_text()
def test_spoken_interview_follows_answer_and_persists_completion(browser_app):
    page, base_url, _ = browser_app
    saved = page.request.post(
        f"{base_url}/api/preparations",
        data={
            "target_role": "Backend Engineer",
            "experience_level": "mid-level",
            "job_description": "",
            "resume_text": "I led a payment API migration and reduced failures.",
        },
    ).json()
    page.add_init_script("""window.SpeechRecognition = class {
      start() { setTimeout(() => this.onresult({results: [[{transcript: 'I moved writes to an idempotent API'}]]}), 10); }
      stop() {}
    };""")
    page.goto(base_url)
    page.get_by_role("button", name="Open preparation").first.click()
    page.get_by_role("button", name="Check microphone").click()
    page.get_by_text("Microphone capture: on (live level check)").wait_for()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.wait_for_timeout(500)
    assert page.locator("#interview-error").is_hidden(), page.locator("#interview-error").evaluate("(element) => element.textContent")
    question = "Tell me about the payment service you built."
    page.get_by_text(f"Interviewer: {question}").wait_for()
    page.get_by_role("button", name="Speak answer").click()
    follow_up = "What trade-off did you make in the payment API migration?"
    page.get_by_text(f"Interviewer: {follow_up}").wait_for()
    page.get_by_role("button", name="Speak answer").click()
    page.wait_for_function("document.querySelectorAll('#transcript li').length >= 5")
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_text("Interview complete.", exact=True).wait_for()
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    assert interview_id
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["turns"][:4] == [
        {"speaker": "Interviewer", "text": question},
        {"speaker": "Candidate", "text": "I moved writes to an idempotent API"},
        {"speaker": "Interviewer", "text": follow_up},
        {"speaker": "Candidate", "text": "I moved writes to an idempotent API"},
    ]
    assert result["turns"][4]["speaker"] == "Interviewer"
    assert result["preparation_id"] == saved["id"]
    assert page.get_by_text("Microphone capture: off").is_visible()
    rejected = page.request.post(
        f"{base_url}/api/interviews/{interview_id}/turns",
        data={"text": "extra answer"},
    )
    assert rejected.status == 409
def test_candidate_can_finish_early_in_browser(browser_app):
    page, base_url, _ = browser_app
    saved = page.request.post(
        f"{base_url}/api/preparations",
        data={
            "target_role": "Backend Engineer",
            "experience_level": "mid-level",
            "job_description": "",
            "resume_text": "I led a payment API migration.",
        },
    ).json()
    page.add_init_script("window.SpeechRecognition = class { start() {} };")
    page.goto(base_url)
    page.get_by_role("button", name="Open preparation").first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_text("Interviewer: Tell me about the payment service you built.").wait_for()
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_role("status").get_by_text("Interview complete.").wait_for()
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["preparation_id"] == saved["id"]


def test_ten_minute_limit_completes_without_another_question(browser_app):
    page, base_url, directory = browser_app
    saved = page.request.post(
        f"{base_url}/api/preparations",
        data={
            "target_role": "Backend Engineer",
            "experience_level": "mid-level",
            "job_description": "",
            "resume_text": "I led a payment API migration.",
        },
    ).json()
    interview = page.request.post(
        f"{base_url}/api/interviews", data={"preparation_id": saved["id"]}
    ).json()
    expired = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with sqlite3.connect(directory / "preparations.sqlite3") as db:
        db.execute("UPDATE interviews SET started_at = ? WHERE id = ?", (expired, interview["id"]))
    result = page.request.post(
        f"{base_url}/api/interviews/{interview['id']}/turns",
        data={"text": "I used idempotency keys to prevent duplicate writes."},
    ).json()
    assert result["status"] == "completed"
    assert result["turns"][-1] == {
        "speaker": "Candidate",
        "text": "I used idempotency keys to prevent duplicate writes.",
    }
    assert len(result["turns"]) == 2
    expired_session = page.request.post(
        f"{base_url}/api/interviews", data={"preparation_id": saved["id"]}
    ).json()
    with sqlite3.connect(directory / "preparations.sqlite3") as db:
        db.execute("UPDATE interviews SET started_at = ? WHERE id = ?", (expired, expired_session["id"]))
    expired_result = page.request.get(f"{base_url}/api/interviews/{expired_session['id']}").json()
    assert expired_result["status"] == "completed"
def test_provider_failure_keeps_answer_and_finishes_with_notice(browser_app):
    page, base_url, _ = browser_app
    saved = page.request.post(
        f"{base_url}/api/preparations",
        data={
            "target_role": "Backend Engineer",
            "experience_level": "mid-level",
            "job_description": "",
            "resume_text": "I led a payment API migration.",
        },
    ).json()
    page.add_init_script("""window.SpeechRecognition = class {
      start() { setTimeout(() => this.onresult({results: [[{transcript: 'trigger provider failure'}]]}), 10); }
      stop() {}
    };""")
    page.goto(base_url)
    page.get_by_role("button", name="Open preparation").first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_text("Interviewer: Tell me about the payment service you built.").wait_for()
    page.get_by_role("button", name="Speak answer").click()
    page.get_by_text("The follow-up could not be generated. Your recognized answer was saved and the interview is complete.").wait_for()
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["turns"][-1] == {"speaker": "Candidate", "text": "trigger provider failure"}
    assert len(result["turns"]) == 2


def test_denied_microphone_permission_has_recovery_message(browser_app):
    page, base_url, _ = browser_app
    page.add_init_script("""Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) }
    });""")
    page.goto(base_url)
    page.get_by_role("button", name="Check microphone").click()
    assert "Allow microphone access in browser settings" in page.get_by_role("alert").inner_text()
    assert page.get_by_text("Microphone capture: off").is_visible()
def test_concurrent_answers_cannot_exceed_follow_up_limit(browser_app):
    page, base_url, _ = browser_app
    saved = page.request.post(
        f"{base_url}/api/preparations",
        data={
            "target_role": "Backend Engineer",
            "experience_level": "mid-level",
            "job_description": "",
            "resume_text": "I led a payment API migration.",
        },
    ).json()
    interview = page.request.post(
        f"{base_url}/api/interviews", data={"preparation_id": saved["id"]}
    ).json()
    page.goto(base_url)
    statuses = page.evaluate(
        """async (id) => {
          const answer = JSON.stringify({text: 'slow answer'});
          const first = fetch(`/api/interviews/${id}/turns`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: answer}).then(r => r.status);
          await new Promise(resolve => setTimeout(resolve, 30));
          const second = await fetch(`/api/interviews/${id}/turns`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: answer});
          return [await first, second.status];
        }""",
        interview["id"],
    )
    assert statuses == [200, 409]
    result = page.request.get(f"{base_url}/api/interviews/{interview['id']}").json()
    assert result["follow_ups_used"] == 1
    assert result["turns"].count({"speaker": "Candidate", "text": "slow answer"}) == 1
    assert len(result["turns"]) == 3


def test_camera_preview_stays_local_during_interview_and_stops_on_completion(browser_app):
    page, base_url, _ = browser_app
    page = page.context.browser.new_page()
    ControlledOpenAIHandler.requests.clear()
    saved = page.request.post(f"{base_url}/api/preparations", data={
        "target_role": "Backend Engineer", "experience_level": "mid-level",
        "job_description": "", "resume_text": "I led a payment API migration.",
    }).json()
    page.add_init_script("""window.SpeechRecognition = class {
      start() { setTimeout(() => this.onresult({results: [[{transcript: 'I used idempotency keys'}]]}), 10); }
      stop() {} abort() {}
    };""")
    requests = []
    page.on("request", lambda request: requests.append((request.url, request.method, request.post_data)) if request.method != "GET" else None)
    page.goto(base_url)
    page.get_by_role("button", name="Enable camera preview").click()
    video = page.locator("#camera-preview")
    page.wait_for_function("document.querySelector('#camera-preview').videoWidth > 0")
    video.evaluate("video => window.previewTrack = video.srcObject.getVideoTracks()[0]")
    assert video.is_visible()
    page.get_by_role("button", name="Open preparation").first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_text("Interviewer: Tell me about the payment service you built.").wait_for()
    assert video.evaluate("video => video.srcObject.getVideoTracks()[0].readyState") == "live"
    page.get_by_role("button", name="Speak answer").click()
    page.get_by_text("Interviewer: What trade-off did you make in the payment API migration?").wait_for()
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_text("Interview complete.", exact=True).wait_for()
    assert video.evaluate("video => video.srcObject === null")
    assert page.evaluate("window.previewTrack.readyState") == "ended"
    assert page.get_by_text("Camera preview: off").is_visible()
    assert requests
    for url, method, data in requests:
        assert url.startswith(base_url + "/api/") and method == "POST"
        payload = json.loads(data or "{}")
        assert set(payload) <= {"preparation_id", "text"}
    assert len(ControlledOpenAIHandler.requests) == 2
    for provider_request in ControlledOpenAIHandler.requests:
        assert set(provider_request) == {"model", "input", "max_output_tokens"}
        assert all(isinstance(message["content"], str) for message in provider_request["input"])
        context = json.loads(provider_request["input"][1]["content"])
        assert set(context) == {"role", "experience", "job_description", "resume", "latest_answer", "question_type", "current_question", "conversation"}
    assert saved["id"]
    page.close()


def test_camera_denial_does_not_block_spoken_interview(browser_app):
    page, base_url, _ = browser_app
    browser = page.context.browser.browser_type.launch(
        headless=True, executable_path=page.context.browser.browser_type.executable_path,
        args=["--use-fake-device-for-media-stream"],
    )
    context = browser.new_context(permissions=["microphone"])
    page = context.new_page()
    page.request.post(f"{base_url}/api/preparations", data={
        "target_role": "Backend Engineer", "experience_level": "mid-level",
        "job_description": "", "resume_text": "I led a payment API migration.",
    })
    page.add_init_script("window.SpeechRecognition = class { start() {} abort() {} };")
    page.goto(base_url)
    page.get_by_role("button", name="Enable camera preview").click()
    page.get_by_text("Camera permission was denied", exact=False).wait_for()
    assert page.get_by_role("button", name="Start 10-minute interview").is_enabled()
    assert page.get_by_role("button", name="Save preparation").is_enabled()
    page.get_by_role("button", name="Open preparation").first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_text("Interviewer: Tell me about the payment service you built.").wait_for()
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_text("Interview complete.", exact=True).wait_for()
    page.close()
    browser.close()


def test_camera_disable_loss_and_leaving_release_capture(browser_app):
    page, base_url, _ = browser_app
    page = page.context.browser.new_page()
    page.goto(base_url)
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').videoWidth > 0")
    page.locator("#camera-preview").evaluate("video => window.track = video.srcObject.getVideoTracks()[0]")
    page.get_by_role("button", name="Disable camera preview").click()
    assert page.evaluate("window.track.readyState") == "ended"
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').srcObject !== null")
    page.locator("#camera-preview").evaluate("""video => {
      window.track = video.srcObject.getVideoTracks()[0];
      window.track.stop();
      window.track.dispatchEvent(new Event('ended'));
    }""")
    page.get_by_text("Camera connection lost", exact=False).wait_for()
    assert page.get_by_role("button", name="Start 10-minute interview").is_enabled()
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').srcObject !== null")
    page.locator("#camera-preview").evaluate("video => window.track = video.srcObject.getVideoTracks()[0]")
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    assert page.evaluate("window.track.readyState") == "ended"
    page.close()
