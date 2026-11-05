import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
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
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
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
        question = ("What trade-off did you make in the payment API migration?"
                    if context["question_type"] == "relevant follow-up"
                    else "Tell me about the payment service you built.")
        body = json.dumps({"output": [{"type": "reasoning", "summary": []}, {
            "type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": question, "annotations": []}
            ],
        }]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    import threading
    import urllib.request

    directory = tmp_path_factory.mktemp("next-preparation")
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ControlledOpenAIHandler)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    api_port, ui_port = free_port(), free_port()
    api_url, base_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
    environment = {**os.environ, "INTERVIEWDADDY_DATABASE": str(directory / "preparations.sqlite3"),
                   "OPENAI_API_KEY": "controlled-test-key", "OPENAI_BASE_URL": f"http://127.0.0.1:{provider.server_port}",
                   "INTERVIEWDADDY_API_ORIGIN": api_url, "NEXT_TELEMETRY_DISABLED": "1"}
    environment.pop("OPENAI_MODEL", None)
    processes = []
    with (directory / "servers.log").open("w") as log:
        try:
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                cwd=ROOT, env=environment, stdout=log, stderr=log, start_new_session=True,
            ))
            processes.append(subprocess.Popen(
                ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(ui_port)],
                cwd=ROOT / "frontend", env=environment, stdout=log, stderr=log, start_new_session=True,
            ))
            for url in [api_url + "/api/preparations", base_url]:
                for _ in range(150):
                    try:
                        urllib.request.urlopen(url, timeout=1).close()
                        break
                    except Exception:
                        if any(process.poll() is not None for process in processes):
                            pytest.fail(f"A server exited; inspect {directory / 'servers.log'}")
                        time.sleep(0.2)
                else:
                    pytest.fail(f"Server not ready at {url}; inspect {directory / 'servers.log'}")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
                yield browser, base_url, directory
                browser.close()
        finally:
            for process in processes:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for process in processes:
                process.wait(timeout=10)
            provider.shutdown()
            provider.server_close()


@pytest.fixture
def browser_app(app_server):
    browser, base_url, directory = app_server
    page = browser.new_page()
    # Each browser test owns its records; completed sessions do not leak into the next journey.
    for preparation in page.request.get(base_url + "/api/preparations").json():
        page.request.delete(base_url + "/api/preparations/" + preparation["id"])
    yield page, base_url, directory
    page.close()


def seed(page, base_url):
    return page.request.post(base_url + "/api/preparations", data={
        "target_role": "Backend Engineer", "experience_level": "mid-level",
        "job_description": "", "resume_text": "I led a payment API migration and reduced failures.",
    }).json()


def devices(page, base_url):
    page.goto(base_url)
    page.get_by_role("button", name="Practise", exact=True).first.click()
    page.get_by_role("button", name="Start 10-minute interview").wait_for()


def speech(page, answer="I moved writes to an idempotent API"):
    page.add_init_script("""window.SpeechRecognition = class {
      start() { this.onstart?.(); setTimeout(() => this.onresult?.({results: [[{transcript: %s}]]}), 10); }
      stop() { this.onend?.(); } abort() { this.onend?.(); }
    };""" % json.dumps(answer))


def start(page):
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.locator("#transcript").get_by_text("Tell me about the payment service you built.", exact=True).wait_for()


def test_candidate_can_correct_save_and_reopen_preparation(browser_app):
    page, base_url, directory = browser_app
    resume = directory / "resume.pdf"
    write_pdf(resume, "Built a dependable payment service used by 20,000 customers.")
    page.goto(base_url)
    page.get_by_label("Resume PDF").set_input_files(resume)
    extracted = page.get_by_label("Extracted resume text")
    expect(extracted).to_have_value("Built a dependable payment service used by 20,000 customers.")
    corrected = "Built a resilient payment service used by 20,000 customers. I led the API migration."
    extracted.fill(corrected)
    page.get_by_label("Target role").fill("Backend Engineer")
    page.get_by_label("Experience level").select_option("mid-level")
    page.get_by_label("Job description (optional)").fill("Own APIs and payment reliability.")
    page.get_by_role("button", name="Save preparation", exact=True).click()
    page.get_by_role("button", name="Open preparation").click()
    expect(extracted).to_have_value(corrected)
    expect(page.get_by_label("Target role")).to_have_value("Backend Engineer")
    expect(page.get_by_label("Experience level")).to_have_value("mid-level")
    expect(page.get_by_label("Job description (optional)")).to_have_value("Own APIs and payment reliability.")
    corrected += " I also documented the migration rollback plan."
    extracted.fill(corrected)
    page.get_by_role("button", name="Save preparation", exact=True).click()
    expect(page.locator("#save-note")).to_have_text("Saved on this device")
    page.reload()
    expect(extracted).to_have_value(corrected)
    records = page.request.get(base_url + "/api/preparations").json()
    assert len(records) == 1
    assert page.request.get(base_url + "/api/preparations/" + records[0]["id"]).json()["resume_text"] == corrected
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete preparation").click()
    expect(page.get_by_role("button", name="Open preparation")).to_have_count(0)
    assert page.request.get(base_url + "/api/preparations").json() == []


def test_invalid_and_unreadable_pdfs_show_actionable_errors(browser_app):
    page, base_url, directory = browser_app
    page.goto(base_url)
    invalid = directory / "resume.txt"
    invalid.write_text("not a PDF")
    page.get_by_label("Resume PDF").set_input_files(invalid)
    expect(page.locator("#error-message")).to_be_visible()
    unreadable = directory / "unreadable.pdf"
    unreadable.write_bytes(b"%PDF-1.4\nthis is not a readable PDF")
    with page.expect_response("**/api/extract") as response:
        page.get_by_label("Resume PDF").set_input_files(unreadable)
    assert response.value.status == 400
    expect(page.locator("#error-message")).to_be_visible()
    image_only = directory / "image-only.pdf"
    write_pdf(image_only, None)
    with page.expect_response("**/api/extract") as response:
        page.get_by_label("Resume PDF").set_input_files(image_only)
    assert response.value.status == 422
    expect(page.locator("#error-message")).to_be_visible()
    expect(page.get_by_label("Extracted resume text")).to_have_value("")


def test_keyboard_user_can_skip_to_form_and_retain_unsaved_edits(browser_app):
    page, base_url, _ = browser_app
    page.goto(base_url)
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    assert page.locator(":focus").evaluate("element => getComputedStyle(element).outlineStyle") != "none"
    page.keyboard.press("Enter")
    expect(page.locator("#main-content")).to_be_focused()
    page.get_by_label("Extracted resume text").fill("My unsaved experience")
    page.get_by_role("button", name="New preparation").click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_label("Extracted resume text")).to_have_value("My unsaved experience")
    page.reload()
    expect(page.get_by_label("Extracted resume text")).to_have_value("My unsaved experience")


def test_spoken_interview_follows_answer_and_persists_completion(browser_app):
    page, base_url, _ = browser_app
    saved = seed(page, base_url)
    speech(page)
    devices(page, base_url)
    page.get_by_role("button", name="Check microphone").click()
    expect(page.locator("#capture-state")).to_contain_text("on (live level check)")
    start(page)
    page.get_by_role("button", name="Speak answer", exact=True).click()
    page.locator("#transcript").get_by_text("What trade-off did you make in the payment API migration?", exact=True).wait_for()
    page.get_by_role("button", name="Speak answer", exact=True).click()
    expect(page.locator("#transcript li")).to_have_count(5)
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_role("button", name="Practice again").wait_for()
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["preparation_id"] == saved["id"]
    assert result["turns"][:4] == [
        {"speaker": "Interviewer", "text": "Tell me about the payment service you built."},
        {"speaker": "Candidate", "text": "I moved writes to an idempotent API"},
        {"speaker": "Interviewer", "text": "What trade-off did you make in the payment API migration?"},
        {"speaker": "Candidate", "text": "I moved writes to an idempotent API"},
    ]
    assert page.request.post(f"{base_url}/api/interviews/{interview_id}/turns", data={"text": "extra answer"}).status == 409
    page.reload()
    expect(page.locator("#transcript li")).to_have_count(5)
    page.get_by_role("button", name="Practice again").click()
    expect(page.get_by_role("button", name="Start 10-minute interview")).to_be_visible()


def test_candidate_can_pause_recover_and_finish_early(browser_app):
    page, base_url, _ = browser_app
    saved = seed(page, base_url)
    page.add_init_script("window.SpeechRecognition = class { start() {} abort() {} };")
    devices(page, base_url)
    start(page)
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    page.get_by_role("button", name="Pause interview").click()
    page.get_by_role("button", name="Resume interview").wait_for()
    page.reload()
    expect(page.get_by_role("button", name="Resume interview")).to_be_enabled()
    expect(page.locator("#capture-state")).to_contain_text("off")
    page.get_by_role("button", name="Resume interview").click()
    page.get_by_role("button", name="Pause interview").wait_for()
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_role("button", name="Practice again").wait_for()
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["preparation_id"] == saved["id"]


def test_ten_minute_limit_completes_without_another_question(browser_app):
    page, base_url, directory = browser_app
    saved = seed(page, base_url)
    interview = page.request.post(base_url + "/api/interviews", data={"preparation_id": saved["id"]}).json()
    expired = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with sqlite3.connect(directory / "preparations.sqlite3") as db:
        db.execute("UPDATE interviews SET started_at = ? WHERE id = ?", (expired, interview["id"]))
    result = page.request.post(f"{base_url}/api/interviews/{interview['id']}/turns", data={"text": "I used idempotency keys."}).json()
    assert result["status"] == "completed"
    assert result["turns"][-1] == {"speaker": "Candidate", "text": "I used idempotency keys."}
    assert len(result["turns"]) == 2
    second = page.request.post(base_url + "/api/interviews", data={"preparation_id": saved["id"]}).json()
    with sqlite3.connect(directory / "preparations.sqlite3") as db:
        db.execute("UPDATE interviews SET started_at = ? WHERE id = ?", (expired, second["id"]))
    assert page.request.get(f"{base_url}/api/interviews/{second['id']}").json()["status"] == "completed"


def test_provider_failure_keeps_answer_and_finishes_with_notice(browser_app):
    page, base_url, _ = browser_app
    seed(page, base_url)
    speech(page, "trigger provider failure")
    devices(page, base_url)
    start(page)
    page.get_by_role("button", name="Speak answer", exact=True).click()
    page.get_by_role("button", name="Practice again").wait_for()
    expect(page.locator("#interview-state")).to_contain_text("recognized answer was saved")
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "completed"
    assert result["turns"][-1] == {"speaker": "Candidate", "text": "trigger provider failure"}
    assert len(result["turns"]) == 2


def test_denied_microphone_permission_has_recovery_message(browser_app):
    page, base_url, _ = browser_app
    seed(page, base_url)
    page.add_init_script("""Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) }
    });""")
    devices(page, base_url)
    page.get_by_role("button", name="Check microphone").click()
    expect(page.locator("#interview-error")).to_contain_text("browser settings")
    expect(page.locator("#capture-state")).to_contain_text("off")
    assert page.request.get(base_url + "/api/preparations").ok


def test_concurrent_answers_cannot_exceed_follow_up_limit(browser_app):
    page, base_url, _ = browser_app
    saved = seed(page, base_url)
    interview = page.request.post(base_url + "/api/interviews", data={"preparation_id": saved["id"]}).json()
    page.goto(base_url)
    statuses = page.evaluate("""async id => {
      const answer = JSON.stringify({text: 'slow answer'});
      const first = fetch(`/api/interviews/${id}/turns`, {method:'POST',headers:{'Content-Type':'application/json'},body:answer}).then(r => r.status);
      await new Promise(resolve => setTimeout(resolve, 30));
      const second = await fetch(`/api/interviews/${id}/turns`, {method:'POST',headers:{'Content-Type':'application/json'},body:answer});
      return [await first, second.status];
    }""", interview["id"])
    assert statuses == [200, 409]
    result = page.request.get(f"{base_url}/api/interviews/{interview['id']}").json()
    assert result["follow_ups_used"] == 1
    assert result["turns"].count({"speaker": "Candidate", "text": "slow answer"}) == 1
    assert len(result["turns"]) == 3


def test_camera_preview_stays_local_during_interview_and_stops_on_completion(browser_app):
    page, base_url, _ = browser_app
    ControlledOpenAIHandler.requests.clear()
    seed(page, base_url)
    speech(page)
    devices(page, base_url)
    requests = []
    page.on("request", lambda request: requests.append((request.url, request.method, request.post_data)) if request.method != "GET" else None)
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').videoWidth > 0")
    video = page.locator("#camera-preview")
    video.evaluate("video => window.previewTrack = video.srcObject.getVideoTracks()[0]")
    expect(video).to_be_visible()
    start(page)
    assert video.evaluate("video => video.srcObject.getVideoTracks()[0].readyState") == "live"
    page.get_by_role("button", name="Speak answer", exact=True).click()
    page.locator("#transcript").get_by_text("What trade-off did you make in the payment API migration?", exact=True).wait_for()
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_role("button", name="Practice again").wait_for()
    assert video.evaluate("video => video.srcObject === null")
    assert page.evaluate("window.previewTrack.readyState") == "ended"
    assert requests
    for url, method, data in requests:
        assert url.startswith(base_url + "/api/") and method == "POST"
        assert set(json.loads(data or "{}")) <= {"preparation_id", "text"}
    assert len(ControlledOpenAIHandler.requests) == 2
    for request in ControlledOpenAIHandler.requests:
        assert set(request) == {"model", "input", "max_output_tokens"}
        assert all(isinstance(message["content"], str) for message in request["input"])
        assert set(json.loads(request["input"][1]["content"])) == {"role", "experience", "job_description", "resume", "latest_answer", "question_type", "current_question", "conversation"}


def test_camera_denial_does_not_block_spoken_interview(browser_app):
    page, base_url, _ = browser_app
    page.add_init_script("""const getMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = constraints => constraints.video
        ? Promise.reject(new DOMException('denied', 'NotAllowedError'))
        : getMedia(constraints);
    """)
    seed(page, base_url)
    speech(page)
    devices(page, base_url)
    page.get_by_role("button", name="Enable camera preview").click()
    expect(page.locator("#camera-state")).to_contain_text("Camera permission was denied")
    expect(page.get_by_role("button", name="Start 10-minute interview")).to_be_enabled()
    start(page)
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_role("button", name="Practice again").wait_for()


def test_camera_disable_loss_and_leaving_release_capture(browser_app):
    page, base_url, _ = browser_app
    seed(page, base_url)
    devices(page, base_url)
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').videoWidth > 0")
    page.locator("#camera-preview").evaluate("video => window.track = video.srcObject.getVideoTracks()[0]")
    page.get_by_role("button", name="Disable camera preview").click()
    assert page.evaluate("window.track.readyState") == "ended"
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').srcObject !== null")
    page.locator("#camera-preview").evaluate("""video => {
      window.track = video.srcObject.getVideoTracks()[0]; window.track.stop(); window.track.dispatchEvent(new Event('ended'));
    }""")
    expect(page.locator("#camera-state")).to_contain_text("Camera connection lost")
    page.get_by_role("button", name="Enable camera preview").click()
    page.wait_for_function("document.querySelector('#camera-preview').srcObject !== null")
    page.locator("#camera-preview").evaluate("video => window.track = video.srcObject.getVideoTracks()[0]")
    page.get_by_role("button", name="Back to preparation").click()
    expect(page.get_by_label("Target role")).to_be_visible()
    assert page.evaluate("window.track.readyState") == "ended"
