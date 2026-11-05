# InterviewDaddy · Spoken resume interview

A local-only resume preparation and spoken interview app. The frontend uses Next.js App Router, React, TypeScript, Tailwind CSS v4, Radix icons, and Framer Motion. The existing FastAPI service owns PDF extraction, SQLite storage, and OpenAI interview reasoning. There are no accounts or public-hosting assumptions.

## Start the app

Create or edit `.env` in the repository root:

```sh
OPENAI_API_KEY=your-key
```

Edit `OPENAI_API_KEY=` in `.env`. `./dev.sh` loads this file automatically. `.env` is git-ignored; never commit or share it.

Install Python 3.12+ and Node.js 20.9+ (a current Node LTS is recommended), then install dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --prefix frontend
./dev.sh
```

Open **http://127.0.0.1:3000**. The launcher runs Next.js on port 3000 and the API on port 8000, loads the root `.env` only into the Python service, and stops both services on Ctrl+C or if either exits. Override ports with `PORT=3010 API_PORT=8010 ./dev.sh`. If frontend dependencies are absent, the launcher installs the lockfile with `npm ci`; Python dependencies must be installed with the command above.

Browser requests to `/api/*` are forwarded by Next.js to FastAPI. For independently launched services, set `INTERVIEWDADDY_API_ORIGIN=http://127.0.0.1:8000` on the Next.js process. API keys never use `NEXT_PUBLIC_*` variables and are never sent to the frontend.

### Production-mode local run

With the Python API running on port 8000:

```sh
npm --prefix frontend run build
npm --prefix frontend run start -- --hostname 127.0.0.1 --port 3000
```

Rewrites are generated at build time: set `INTERVIEWDADDY_API_ORIGIN` during **both build and development** when using a different API origin. `npm --prefix frontend run typecheck` checks TypeScript. Geist fonts are bundled locally; the UI does not request a font or animation CDN.

The server binds to loopback (`127.0.0.1`) so the app is available only on this device by default. Do not expose it to a network or public host without adding appropriate access controls.

OpenAI HTTPS requests use the `certifi` CA bundle from `requirements.txt`, including on Python installations without a system CA bundle. TLS certificate verification remains enabled.

## Prepare a resume

1. Upload a text-based PDF (up to 8 MB), or paste resume text. Scanned image PDFs are not supported; OCR is not included.
2. Review and edit the extracted resume text.
3. Add a target role and experience level. A job description is optional.
4. **Save preparation** keeps you in the editor. **Continue to audio** saves changes and opens device setup.
5. Saved preparations offer **Practise** to go directly to audio setup, **Open preparation** to edit, and **Delete** to remove the preparation and its associated interviews. Switching with unsaved changes offers Save, Discard, and Cancel. Same-tab drafts and the current setup screen survive refresh when browser storage is available.

Saved resume and job-description text remain in local SQLite until deletion. An interview sends resume context and completed text answers to OpenAI for reasoning. Browser SpeechRecognition may send microphone audio to the browser platform's service; audio and video are not stored by this app. Downloaded copies and provider retention are separate from local deletion. Ordinary OpenAI API access requires an API key and API billing; a ChatGPT subscription does not grant API access.

The optional **Enable camera preview** control appears in audio setup and remains available in the interview. Video is not uploaded, recorded, stored in the transcript, or assessed. Denying access or losing a camera does not prevent an interview. Disable the preview to stop capture; camera tracks also stop when you leave audio setup, leave the page, or the interview ends. Re-enable it if you want a preview for another session.

## Run a spoken interview

Set `OPENAI_API_KEY` in the repository-root `.env` file before launching. `./dev.sh` loads it server-side. The default model is `gpt-6-luna`; override with `OPENAI_MODEL` if needed. API credits and usage are subject to the OpenAI organization's limits and billing. The interviewer uses one LangGraph workflow for up to 10 minutes, with one follow-up per topic before moving on. Questions use the saved preparation and completed conversation, with depth adjusted to the experience level. You can finish early. The transcript stores recognized text and speaker attribution, not raw audio. If question generation fails, the recognized answer remains saved and the interview completes.

Use a supported browser with microphone and speech synthesis support. Choose **Check microphone** and **Test speaker** before starting. Allow microphone permission when asked. Browser recognition support and audio processing vary by browser; check its privacy policy.

During the interview, the status shows when the interviewer is speaking, listening, or thinking; the answer button is disabled while listening or processing. If recognition fails, check the displayed recovery guidance and retry.

Choose **Speak answer** to activate recognition and interrupt playback, or use **Interrupt playback** without activating the microphone. Recognition submits the completed result; the interface is not an always-listening conversation. **Ask for help** contains repetition, rephrasing, thinking time, and hint controls. Hints are labelled in the transcript and retained as assistance evidence, not independent answers. Recognition errors can appear in the transcript.

Use **Pause interview** to stop microphone capture and playback; paused time does not count toward the 10-minute limit. Resume returns to the saved question. Refreshing the same browser tab restores the saved transcript and session state. If the connection is lost, use **Recover connection** or wait for reconnection; check the saved transcript before re-speaking an interrupted answer. Partial speech is not saved as an answer. Time continues while disconnected unless you paused successfully before the interruption.

The interviewer will not start without a saved preparation and configured API key. Keep the app bound to loopback and do not expose it publicly.

Completed sessions open a transcript review with **Practice again** and **Back to preparation**. There are no automated scores. Refresh restores the current session without automatically reactivating the microphone. The migration retains the Python API and existing saved preparations; browser drafts are specific to their origin, so a draft from an older port is not automatically available at port 3000.

## Run browser checks

Install the test dependencies and Chromium once:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
npm ci --prefix frontend
.venv/bin/python -m pytest -q
```

The browser journey tests launch both FastAPI and Next.js with a temporary SQLite database, then exercise the real UI and same-origin API proxy in Chromium. Stop a running Next.js development instance in this checkout before running the suite, since Next.js locks its development output directory. Speech recognition and provider responses are controlled test boundaries, not proof of physical microphone quality or live provider behavior.

## Frontend migration verification

The Next.js replacement passed all 34 pytest checks and a production build with strict TypeScript enabled. Production-mode Chromium checks covered preparation save, audio setup, refresh restoration, return navigation, and 320/390/1440px layouts without horizontal overflow. Interview and review surfaces were also inspected with controlled speech and interview responses; the regression suite exercises the real Python API with a controlled provider.

Physical microphones, real speech recognition quality, and live OpenAI responses were not verified by this migration. The test run still reports existing FastAPI startup-event and LangGraph dependency deprecation warnings.
