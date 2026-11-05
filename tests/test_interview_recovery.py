from test_preparation_browser import app_server, browser_app


def test_pause_refresh_and_recover_partial_answer(browser_app):
    page, base_url, _ = browser_app
    page.request.post(f"{base_url}/api/preparations", data={"resume_text": "Built a payment service", "target_role": "Engineer", "experience_level": "entry", "job_description": ""})
    page.add_init_script("""window.SpeechRecognition = class {
      start() { window.recognition = this; this.onstart?.(); }
      abort() { window.aborted = true; } stop() {}
    };""")
    page.goto(base_url)
    page.get_by_role("button", name="Practise", exact=True).first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_role("button", name="Speak answer").click()
    page.get_by_role("button", name="Pause interview").click()
    page.get_by_text("Paused", exact=False).first.wait_for()
    assert page.evaluate("window.aborted")
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    paused = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert paused["status"] == "paused"
    assert len(paused["turns"]) == 1
    page.reload()
    page.get_by_text("An interrupted answer may have been lost", exact=False).wait_for()
    page.get_by_role("button", name="Resume interview").click()
    page.get_by_text("Ready for your answer.").wait_for()
    assert page.request.get(f"{base_url}/api/interviews/{interview_id}").json()["question"] == paused["question"]
    page.get_by_role("button", name="Speak answer").click()
    page.evaluate("window.recognition.onresult({results: [[{transcript: 'I built the API'}]]})")
    page.locator("#transcript").get_by_text("I built the API", exact=True).wait_for()
    assert len(page.request.get(f"{base_url}/api/interviews/{interview_id}").json()["turns"]) == 3


def test_reconnect_preserves_order_and_paused_time(browser_app):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    page, base_url, directory = browser_app
    prep = page.request.post(f"{base_url}/api/preparations", data={"resume_text": "Built a payment service", "target_role": "Engineer", "experience_level": "entry", "job_description": ""}).json()
    interview = page.request.post(f"{base_url}/api/interviews", data={"preparation_id": prep["id"]}).json()
    url = f"{base_url}/api/interviews/{interview['id']}"
    answered = page.request.post(f"{url}/turns", data={"text": "I built the API"}).json()
    page.goto(base_url)
    page.evaluate("(id) => sessionStorage.setItem('interview-id', id)", interview["id"])
    page.reload()
    page.locator("#transcript").get_by_text("I built the API", exact=True).wait_for()
    page.context.set_offline(True)
    page.get_by_text("Connection lost", exact=False).first.wait_for()
    page.context.set_offline(False)
    page.get_by_text("Connection: connected").wait_for()
    assert page.locator("#transcript li > p").all_text_contents() == [turn["text"] for turn in answered["turns"]]
    page.get_by_role("button", name="Pause interview").click()
    page.get_by_text("Paused", exact=False).first.wait_for()
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(directory / "preparations.sqlite3") as db:
        db.execute("UPDATE interviews SET started_at = ?, paused_at = ? WHERE id = ?", (old, old, interview["id"]))
    page.reload()
    page.get_by_role("button", name="Resume interview").click()
    page.get_by_text("Ready for your answer.").wait_for()
    restored = page.request.get(url).json()
    assert restored["status"] == "active"
    assert restored["follow_ups_used"] == answered["follow_ups_used"]
    assert restored["turns"] == answered["turns"]
    assert restored["remaining_seconds"] > 590
    page.get_by_role("button", name="Finish interview").click()
    page.get_by_text("Interview complete.", exact=True).wait_for()
    assert page.request.post(f"{url}/resume").json()["status"] == "completed"
