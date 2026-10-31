# InterviewDaddy · Spoken resume interview

A local-only resume preparation and spoken interview app. There are no accounts or public-hosting assumptions.

## Start the app

If `.env` does not exist yet, create it from the template:

```sh
cp .env.example .env
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

## Prepare a resume

1. Choose a text-based PDF (up to 8 MB). Scanned image PDFs are not supported; OCR is not included.
2. Review and edit the extracted resume text.
3. Add a target role and experience level. A job description is optional.
4. Save the preparation. Use **Open preparation** to reopen it or **Delete** to remove it from this device.

Saved resume and job-description text remain in local SQLite until deletion. An interview sends resume context and completed text answers to OpenAI for reasoning. Browser SpeechRecognition may send microphone audio to the browser platform's service; audio and video are not stored by this app. Downloaded copies and provider retention are separate from local deletion. Ordinary OpenAI API access requires an API key and API billing; a ChatGPT subscription does not grant API access.

## Run a spoken interview

Set `OPENAI_API_KEY` in the server environment before launching the app. The key stays on the server. API credits and usage are subject to the OpenAI organization's limits and billing. The interviewer uses one LangGraph workflow and allows up to 10 minutes, one opening question, and one answer-based follow-up. You can finish early. The transcript stores recognized text and speaker attribution, not raw audio. If follow-up generation fails, the recognized answer remains saved and the interview completes.

Use a supported browser with microphone and speech synthesis support. Choose **Check microphone** and **Test speaker** before starting. Allow microphone permission when asked. Browser recognition support and audio processing vary by browser; check its privacy policy.

The interviewer will not start without a saved preparation and configured API key. Keep the app bound to loopback and do not expose it publicly.

## Run browser checks

Install the test dependencies and Chromium once:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
pytest -q
```

The browser journey tests run the real FastAPI server with a temporary SQLite database and exercise the visible page in Chromium.
