# InterviewDaddy · Spoken resume interview

A local-only resume preparation and spoken interview app. There are no accounts or public-hosting assumptions.

## Start the app

Create or edit `.env` in the repository root:

```sh
OPENAI_API_KEY=your-key
```

Edit `OPENAI_API_KEY=` in `.env`. `./dev.sh` loads this file automatically. `.env` is git-ignored; never commit or share it.

Run the launcher from this directory:
```sh
./dev.sh
```

It creates `.venv` if needed, installs or updates the dependencies from
`requirements.txt`, and starts the app on an available local port. Uvicorn prints
the URL to open in your browser (for example, `http://127.0.0.1:54321`). Stop
the server with `Ctrl+C`.

The server binds to loopback (`127.0.0.1`) so the app is available only on this device by default. Do not expose it to a network or public host without adding appropriate access controls.

OpenAI HTTPS requests use the `certifi` CA bundle from `requirements.txt`, including on Python installations without a system CA bundle. TLS certificate verification remains enabled.

## Prepare a resume

1. Choose a text-based PDF (up to 8 MB). Scanned image PDFs are not supported; OCR is not included.
2. Review and edit the extracted resume text.
3. Add a target role and experience level. A job description is optional.
4. Save the preparation. Use **Open preparation** to reopen it or **Delete** to remove it from this device.

Saved resume and job-description text remain in local SQLite until deletion. An interview sends resume context and completed text answers to OpenAI for reasoning. Browser SpeechRecognition may send microphone audio to the browser platform's service; audio and video are not stored by this app. Downloaded copies and provider retention are separate from local deletion. Ordinary OpenAI API access requires an API key and API billing; a ChatGPT subscription does not grant API access.

The optional **Enable camera preview** control displays video locally during preparation and the interview. Video is not uploaded, recorded, stored in the transcript, or assessed. Denying access or losing a camera does not prevent an interview. Disable the preview to stop capture; camera tracks also stop when you leave the page or the interview ends. Re-enable it if you want a preview for another session.

## Run a spoken interview

Set `OPENAI_API_KEY` in the repository-root `.env` file before launching. `./dev.sh` loads it server-side. The default model is `gpt-6-luna`; override with `OPENAI_MODEL` if needed. API credits and usage are subject to the OpenAI organization's limits and billing. The interviewer uses one LangGraph workflow for up to 10 minutes, with one follow-up per topic before moving on. Questions use the saved preparation and completed conversation, with depth adjusted to the experience level. You can finish early. The transcript stores recognized text and speaker attribution, not raw audio. If question generation fails, the recognized answer remains saved and the interview completes.

Use a supported browser with microphone and speech synthesis support. Choose **Check microphone** and **Test speaker** before starting. Allow microphone permission when asked. Browser recognition support and audio processing vary by browser; check its privacy policy.

During the interview, the status shows when the interviewer is speaking, listening, or thinking; the answer button is disabled while listening or processing. If recognition fails, check the displayed recovery guidance and retry.

Use **Interrupt playback** or start speaking to stop the current question. You can request repetition, rephrasing, thinking time, or a hint using the on-screen controls. Hints are labelled in the transcript and retained as assessment evidence; they are not presented as independent answers. Recognition errors can appear in the transcript.

Use **Pause interview** to stop microphone capture and playback; paused time does not count toward the 10-minute limit. Resume returns to the saved question. Refreshing the same browser tab restores the saved transcript and session state. If the connection is lost, use **Recover connection** or wait for reconnection; check the saved transcript before re-speaking an interrupted answer. Partial speech is not saved as an answer. Time continues while disconnected unless you paused successfully before the interruption.

The interviewer will not start without a saved preparation and configured API key. Keep the app bound to loopback and do not expose it publicly.

## Run browser checks

Install the test dependencies and Chromium once:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
```

The browser journey tests run the real FastAPI server with a temporary SQLite database and exercise the visible page in Chromium.
