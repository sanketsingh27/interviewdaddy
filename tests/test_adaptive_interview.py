from test_preparation_browser import app_server, browser_app


def test_assistance_and_repeat_are_recorded_without_consuming_answer(browser_app):
    page, base_url, _ = browser_app
    prep = page.request.post(f"{base_url}/api/preparations", data={"resume_text": "Built a payment service", "target_role": "Engineer", "experience_level": "entry", "job_description": ""}).json()
    interview = page.request.post(f"{base_url}/api/interviews", data={"preparation_id": prep["id"]}).json()
    url = f"{base_url}/api/interviews/{interview['id']}/actions"
    repeat = page.request.post(url, data={"action": "repeat"})
    assert repeat.ok
    assert repeat.json()["question"] == interview["question"]
    hint = page.request.post(url, data={"action": "hint"})
    assert hint.ok
    result = page.request.get(f"{base_url}/api/interviews/{interview['id']}").json()
    assert result["assessment_evidence"]
    assert any(turn.get("assistance") for turn in result["turns"])


def test_browser_can_interrupt_repeat_and_move_on_after_uncertainty(browser_app):
    page, base_url, _ = browser_app
    page.request.post(f"{base_url}/api/preparations", data={
        "resume_text": "I built a payment service", "target_role": "Engineer",
        "experience_level": "entry", "job_description": "Maintain reliable APIs",
    })
    page.add_init_script("""window.SpeechRecognition = class {
      start() { setTimeout(() => { this.onresult({results: [[{transcript: "I don't know"}]]}); this.onend(); }, 10); }
      stop() {} abort() {}
    };""")
    page.goto(base_url)
    page.get_by_role("button", name="Practise", exact=True).first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.locator("#transcript li").first.wait_for()
    page.get_by_role("button", name="Interrupt playback").click()
    page.get_by_text("Ask for help", exact=True).click()
    page.get_by_role("button", name="Repeat question").click()
    page.wait_for_function("document.querySelectorAll('#transcript li').length === 3")
    page.get_by_text("Ask for help", exact=True).click()
    page.get_by_role("button", name="Request a hint").click()
    page.wait_for_function("document.querySelectorAll('#transcript li').length === 5")
    page.get_by_role("button", name="Speak answer").click()
    page.wait_for_function("document.querySelectorAll('#transcript li').length === 7")
    page.get_by_role("button", name="Speak answer").click()
    page.wait_for_function("document.querySelectorAll('#transcript li').length === 9")
    interview_id = page.locator("#transcript").get_attribute("data-interview-id")
    result = page.request.get(f"{base_url}/api/interviews/{interview_id}").json()
    assert result["status"] == "active"
    assert result["follow_ups_used"] == 0
    assert len(result["assessment_evidence"]) == 1
    assert sum(turn["speaker"] == "Candidate" and turn["text"] == "I don't know" for turn in result["turns"]) == 2
    page.get_by_role("button", name="Finish interview").click()


def test_speech_status_tracks_listening_processing_and_playback(browser_app):
    page, base_url, _ = browser_app
    page.set_default_timeout(3000)
    page.request.post(f"{base_url}/api/preparations", data={
        "resume_text": "I built a payment service", "target_role": "Engineer",
        "experience_level": "entry", "job_description": "",
    })
    page.add_init_script("""window.SpeechRecognition = class {
      start() { window.recognition = this; this.onstart?.(); }
      stop() {} abort() {}
    };
    window.speechSynthesis.cancel = () => {};
    window.speechSynthesis.speak = utterance => { window.utterance = utterance; utterance.onstart?.(); };
    """)
    page.goto(base_url)
    page.get_by_role("button", name="Practise", exact=True).first.click()
    page.get_by_role("button", name="Start 10-minute interview").click()
    page.get_by_text("Interviewer is speaking.", exact=True).wait_for()
    page.get_by_role("button", name="Speak answer").click()
    page.get_by_text("Listening to your answer.", exact=True).wait_for()
    assert page.get_by_role("button", name="Listening…").is_disabled()
    page.evaluate("() => { window.recognition.onresult({results: [[{transcript: 'slow answer'}]]}); }")
    page.get_by_text("Thinking about your answer…", exact=True).wait_for()
    page.get_by_text("Interviewer is speaking.", exact=True).wait_for()
    page.evaluate("window.utterance.onend()")
    page.get_by_text("Ready for your answer.", exact=True).wait_for()
    assert page.get_by_role("button", name="Speak answer").is_enabled()
    page.get_by_role("button", name="Speak answer").click()
    page.evaluate("window.recognition.onerror({error: 'no-speech'})")
    page.get_by_text("No speech was heard.", exact=False).wait_for()
    assert page.get_by_role("button", name="Speak answer").is_enabled()
