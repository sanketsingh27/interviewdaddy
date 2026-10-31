# InterviewDaddy · Resume preparation

A local-only resume preparation app. There are no accounts, live AI calls, voice features, or public-hosting assumptions in this slice.

## Start the app

1. Use Python 3.11 or newer.
2. From this directory, create and activate a virtual environment:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the app dependencies and start the local server:

   ```sh
   python -m pip install -r requirements.txt
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. Open <http://127.0.0.1:8000> in your browser. Stop the server with `Ctrl+C`.

The server binds to loopback (`127.0.0.1`) so the app is available only on this device by default. Do not expose it to a network or public host without adding appropriate access controls.

## Prepare a resume

1. Choose a text-based PDF (up to 8 MB). Scanned image PDFs are not supported; OCR is not included.
2. Review and edit the extracted resume text.
3. Add a target role and experience level. A job description is optional.
4. Save the preparation. Use **Open preparation** to reopen it or **Delete** to remove it from this device.

The app retains saved resume and job-description text in `data/preparations.sqlite3` until you delete each preparation. This preparation step makes no AI-provider request. A later interview feature may send text to OpenAI for reasoning under that provider's policies; downloaded files and provider-side retention are separate from local deletion. Resume and job-description contents are untrusted reference data and must never be treated as model instructions.

## Run browser checks

Install the test dependencies and Chromium once:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
pytest -q
```

The browser journey tests run the real FastAPI server with a temporary SQLite database and exercise the visible page in Chromium.
