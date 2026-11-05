"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  SpeakerLoudIcon,
  PlayIcon,
  PauseIcon,
  StopIcon,
  ReloadIcon,
  VideoIcon,
  LockClosedIcon,
  ChatBubbleIcon,
} from "@radix-ui/react-icons";
import {
  api,
  post,
  errorText,
  storedInterviewId,
  type Preparation,
} from "../lib/api";
import { MagneticButton, VoiceMark } from "./motion";

type Turn = {
  speaker: string;
  text: string;
  assistance?: string;
  action?: string;
};
type Session = {
  id: string;
  preparation_id: string;
  status: "active" | "paused" | "completed";
  question: string;
  spoken?: string;
  notice?: string;
  turns: Turn[];
  processing: boolean;
  remaining_seconds: number;
};
type RecognitionResult = {
  results: { [index: number]: { [index: number]: { transcript: string } } };
};
type Recognition = {
  lang: string;
  interimResults: boolean;
  onstart: (() => void) | null;
  onresult: ((event: RecognitionResult) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
type Actions = {
  mic: () => void;
  speaker: () => void;
  camera: () => void;
  start: () => void;
  answer: () => void;
  interrupt: () => void;
  pause: () => void;
  finish: () => void;
  recover: () => void;
  help: (action: string) => void;
  leave: () => void;
  again: () => void;
};
const initialActions: Actions = {
  mic() {},
  speaker() {},
  camera() {},
  start() {},
  answer() {},
  interrupt() {},
  pause() {},
  finish() {},
  recover() {},
  help() {},
  leave() {},
  again() {},
};

export default function InterviewStudio({
  preparation,
  onBack,
}: {
  preparation: Preparation;
  onBack: () => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [state, setState] = useState("Ready when you are.");
  const [mode, setMode] = useState("ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [connection, setConnection] = useState("Connection: ready");
  const [capture, setCapture] = useState("Microphone capture: off");
  const [cameraState, setCameraState] = useState("Camera preview: off");
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraPending, setCameraPending] = useState(false);
  const [micChecked, setMicChecked] = useState(false);
  const [speakerChecked, setSpeakerChecked] = useState(false);
  const [seconds, setSeconds] = useState(600);
  const [supported, setSupported] = useState(true);
  const actions = useRef<Actions>(initialActions);
  const video = useRef<HTMLVideoElement>(null);
  const meter = useRef<HTMLProgressElement>(null);
  const transcript = useRef<HTMLOListElement>(null);
  const onBackRef = useRef(onBack);
  onBackRef.current = onBack;

  useEffect(() => {
    let live = true,
      current: Session | null = null,
      pending = false,
      restoring = false;
    let recognition: Recognition | null = null,
      utterance: SpeechSynthesisUtterance | null = null;
    let microphone: MediaStream | null = null,
      camera: MediaStream | null = null,
      context: AudioContext | null = null;
    let cameraVersion = 0,
      micVersion = 0,
      cameraWaiting = false,
      playbackVersion = 0;
    let frame = 0,
      clock: ReturnType<typeof setInterval> | undefined,
      poll: ReturnType<typeof setTimeout> | undefined;
    const Speech =
      (window as SpeechWindow).SpeechRecognition ||
      (window as SpeechWindow).webkitSpeechRecognition;
    setSupported(Boolean(Speech && window.speechSynthesis));
    function store(key: string, value: string | null) {
      try {
        if (value === null) sessionStorage.removeItem(key);
        else sessionStorage.setItem(key, value);
      } catch {
        if (live)
          setError(
            "Browser storage is unavailable. Keep this tab open; refresh cannot restore this interview.",
          );
      }
    }
    function read(key: string) {
      try {
        return sessionStorage.getItem(key);
      } catch {
        return null;
      }
    }
    function updateMode(value: string, message?: string) {
      if (!live) return;
      setMode(value);
      setState(
        message ||
          {
            ready: "Ready for your answer.",
            listening: "Listening to your answer.",
            thinking: "Thinking about your answer…",
            speaking: "Interviewer is speaking.",
            paused: "Paused. Resume when you are ready.",
            completed: "Interview complete.",
          }[value] ||
          value,
      );
    }
    function stopPlayback() {
      playbackVersion++;
      utterance = null;
      window.speechSynthesis?.cancel();
    }
    function stopMicrophone() {
      micVersion++;
      cancelAnimationFrame(frame);
      frame = 0;
      const stream = microphone;
      microphone = null;
      stream?.getTracks().forEach((track) => track.stop());
      void context?.close();
      context = null;
      if (meter.current) meter.current.value = 0;
      if (live) setCapture("Microphone capture: off");
    }
    function stopCapture() {
      const active = recognition;
      recognition = null;
      active?.abort();
      stopPlayback();
      stopMicrophone();
    }
    function stopCamera(message = "Camera preview: off") {
      cameraVersion++;
      cameraWaiting = false;
      camera?.getTracks().forEach((track) => track.stop());
      camera = null;
      if (video.current) video.current.srcObject = null;
      if (live) {
        setCameraState(message);
        setCameraOn(false);
        setCameraPending(false);
      }
    }
    async function openMic() {
      if (microphone?.active) return true;
      const version = ++micVersion;
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (!live || version !== micVersion) {
          stream.getTracks().forEach((track) => track.stop());
          return false;
        }
        microphone = stream;
        stream.getAudioTracks()[0]?.addEventListener("ended", () => {
          if (microphone !== stream) return;
          stopCapture();
          setMicChecked(false);
          setError("Microphone disconnected. Reconnect it and try again.");
          updateMode("ready");
        });
        setCapture("Microphone capture: on (live level check)");
        setMicChecked(true);
        context = new AudioContext();
        const analyser = context.createAnalyser();
        context.createMediaStreamSource(stream).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        const tick = () => {
          if (!live || microphone !== stream) return;
          analyser.getByteTimeDomainData(samples);
          let peak = 0;
          for (const value of samples)
            peak = Math.max(peak, Math.abs(value - 128));
          if (meter.current) meter.current.value = Math.min(100, peak * 2);
          frame = requestAnimationFrame(tick);
        };
        tick();
        return true;
      } catch (e) {
        if (live && version === micVersion) {
          stopMicrophone();
          setMicChecked(false);
          setError(
            e instanceof DOMException && e.name === "NotAllowedError"
              ? "Microphone permission was denied. Allow access in browser settings, then retry."
              : "No usable microphone was found. Connect a microphone and try again.",
          );
        }
        return false;
      }
    }
    function speak(text: string) {
      if (!live || current?.status !== "active") return;
      stopPlayback();
      if (!window.speechSynthesis) {
        setError("Speech playback is not supported in this browser.");
        return;
      }
      const spoken = new SpeechSynthesisUtterance(text);
      utterance = spoken;
      spoken.onstart = () => {
        if (live && utterance === spoken) updateMode("speaking");
      };
      spoken.onend = () => {
        if (live && utterance === spoken) {
          utterance = null;
          updateMode("ready");
        }
      };
      spoken.onerror = () => {
        if (live && utterance === spoken) {
          utterance = null;
          updateMode("ready");
          setError(
            "Playback failed. Read the question in the transcript or check your speaker and retry.",
          );
        }
      };
      updateMode("speaking");
      window.speechSynthesis.speak(spoken);
    }
    function apply(result: Session) {
      if (!live) return;
      current = result;
      setSession(result);
      store("interview-id", result.id);
      clearInterval(clock);
      clearTimeout(poll);
      setSeconds(Math.ceil(result.remaining_seconds));
      if (result.status === "completed") {
        stopCapture();
        stopCamera();
        pending = false;
        setBusy(false);
        restoring = false;
        setRecovering(false);
        updateMode("completed", result.notice || "Interview complete.");
        return;
      }
      if (result.status === "paused") updateMode("paused");
      else {
        const at = Date.now();
        clock = setInterval(() => {
          const left = Math.max(
            0,
            Math.ceil(result.remaining_seconds - (Date.now() - at) / 1000),
          );
          if (live) setSeconds(left);
          if (left === 0 && !restoring) {
            clearInterval(clock);
            void finish();
          }
        }, 1000);
        updateMode(result.processing ? "thinking" : "ready");
      }
      if (result.processing) {
        restoring = true;
        setRecovering(true);
        poll = setTimeout(() => void recover(), 500);
      }
    }
    async function recover() {
      let id = current?.id;
      if (!id) {
        try {
          id = storedInterviewId() || undefined;
        } catch {
          return;
        }
      }
      if (!id || !live) return;
      restoring = true;
      setRecovering(true);
      stopCapture();
      clearTimeout(poll);
      setConnection("Connection: recovering…");
      try {
        const result = await api<Session>(
          `/api/interviews/${encodeURIComponent(id)}`,
        );
        if (!live) return;
        restoring = false;
        setRecovering(false);
        setConnection("Connection: connected");
        apply(result);
        if (read("interview-partial") === id) {
          setError(
            "An interrupted answer may have been lost. Check the saved transcript and speak it again if needed.",
          );
          store("interview-partial", null);
        }
      } catch (e) {
        if (live) {
          setConnection(
            "Connection lost. Recover connection to check saved answers.",
          );
          setError(errorText(e));
        }
      }
    }
    async function finish() {
      if (!current || current.status === "completed" || !live) return;
      const id = current.id;
      if (recognition) setError("Your unfinished answer was not saved.");
      stopCapture();
      clearInterval(clock);
      pending = true;
      setBusy(true);
      try {
        const result = await post<Session>(`/api/interviews/${id}/finish`);
        if (live) {
          store("interview-partial", null);
          apply(result);
        }
      } catch (e) {
        if (live) {
          setError(errorText(e));
          await recover();
        }
      } finally {
        pending = false;
        if (live) setBusy(false);
      }
    }
    async function send(text: string, action?: string) {
      if (
        !current ||
        current.status !== "active" ||
        pending ||
        restoring ||
        !live
      )
        return;
      const id = current.id;
      stopPlayback();
      const version = playbackVersion;
      pending = true;
      setBusy(true);
      updateMode("thinking");
      try {
        const result = await post<Session>(
          `/api/interviews/${id}/${action ? "actions" : "turns"}`,
          action ? { action } : { text },
        );
        if (!live || current.id !== id || current.status !== "active") return;
        store("interview-partial", null);
        apply(result);
        if (result.status === "active" && version === playbackVersion)
          speak(result.spoken || result.question);
      } catch (e) {
        if (live) {
          setError(errorText(e));
          await recover();
        }
      } finally {
        pending = false;
        if (live) setBusy(false);
      }
    }
    actions.current = {
      mic() {
        if (microphone) stopMicrophone();
        else {
          setError("");
          void openMic();
        }
      },
      speaker() {
        if (!window.speechSynthesis) {
          setError("Speech playback is not supported in this browser.");
          return;
        }
        stopPlayback();
        const sample = new SpeechSynthesisUtterance(
          "Speaker check. If you can hear this, playback is working.",
        );
        sample.onerror = () => {
          if (live) {
            setSpeakerChecked(false);
            setError(
              "Speaker playback failed. Check your audio output and retry.",
            );
          }
        };
        window.speechSynthesis.speak(sample);
        setSpeakerChecked(true);
      },
      camera() {
        if (camera || cameraWaiting) {
          stopCamera();
          return;
        }
        const version = ++cameraVersion;
        cameraWaiting = true;
        setCameraPending(true);
        setCameraState(
          "Waiting for camera permission. You can continue without it.",
        );
        void navigator.mediaDevices
          .getUserMedia({ video: true, audio: false })
          .then((stream) => {
            if (!live || version !== cameraVersion) {
              stream.getTracks().forEach((track) => track.stop());
              return;
            }
            cameraWaiting = false;
            camera = stream;
            if (video.current) video.current.srcObject = stream;
            setCameraPending(false);
            setCameraOn(true);
            setCameraState("Camera preview: on");
            stream.getVideoTracks()[0]?.addEventListener("ended", () => {
              if (camera === stream)
                stopCamera(
                  "Camera connection lost. You can continue without it.",
                );
            });
          })
          .catch((e) => {
            if (live && version === cameraVersion)
              stopCamera(
                e.name === "NotAllowedError"
                  ? "Camera permission was denied. You can continue without it or allow access in browser settings."
                  : "Camera unavailable. You can continue without it or connect a camera and retry.",
              );
          });
      },
      start() {
        if (pending || current || !live) return;
        if (!Speech || !window.speechSynthesis) {
          setError(
            "Spoken interviews need a supported browser such as Chrome or Edge.",
          );
          return;
        }
        pending = true;
        setBusy(true);
        setError("");
        void (async () => {
          try {
            if (!(await openMic()) || !live) return;
            const result = await post<Session>("/api/interviews", {
              preparation_id: preparation.id,
            });
            if (!live) return;
            apply(result);
            setConnection("Connection: connected");
            speak(result.question);
          } catch (e) {
            if (live) {
              stopCapture();
              setError(errorText(e));
            }
          } finally {
            pending = false;
            if (live) setBusy(false);
          }
        })();
      },
      answer() {
        if (
          !Speech ||
          !current ||
          current.status !== "active" ||
          pending ||
          restoring ||
          recognition
        )
          return;
        setError("");
        stopPlayback();
        const active = new Speech();
        const id = current.id;
        let submitted = false;
        recognition = active;
        active.lang = "en-US";
        active.interimResults = false;
        active.onstart = () => {
          if (live && recognition === active) {
            setCapture("Microphone capture: on (listening)");
            updateMode("listening");
          }
        };
        active.onresult = (event) => {
          if (
            !live ||
            submitted ||
            recognition !== active ||
            current?.id !== id ||
            current.status !== "active"
          )
            return;
          submitted = true;
          recognition = null;
          active.stop();
          stopMicrophone();
          const text = event.results[0]?.[0]?.transcript?.trim();
          if (text) void send(text);
          else {
            updateMode("ready");
            setError("No speech was heard. Try speaking again.");
          }
        };
        active.onerror = (event) => {
          if (!live || recognition !== active) return;
          recognition = null;
          stopMicrophone();
          store("interview-partial", null);
          updateMode("ready");
          const messages: Record<string, string> = {
            "not-allowed":
              "Microphone permission was denied. Allow access in browser settings and retry.",
            "no-speech":
              "No speech was heard. Check your microphone level and try speaking again.",
            "audio-capture":
              "No microphone is available. Connect or enable one, then retry.",
            network:
              "Speech recognition could not connect. Check your network or try another supported browser.",
          };
          setError(
            messages[event.error] ||
              `Speech recognition failed (${event.error}). Check your microphone and retry.`,
          );
        };
        active.onend = () => {
          if (live && recognition === active) {
            recognition = null;
            stopMicrophone();
            if (!submitted) {
              store("interview-partial", null);
              updateMode("ready");
            }
          }
        };
        store("interview-partial", id);
        updateMode("listening");
        try {
          active.start();
        } catch {
          recognition = null;
          stopMicrophone();
          store("interview-partial", null);
          updateMode("ready");
          setError(
            "Speech recognition could not start. Check your microphone and retry.",
          );
        }
      },
      interrupt() {
        stopPlayback();
        if (!recognition && !pending && current?.status === "active")
          updateMode("ready");
      },
      pause() {
        if (!current || current.status === "completed" || pending || restoring)
          return;
        const id = current.id,
          resume = current.status === "paused";
        if (recognition)
          setError(
            "Your interrupted answer was not saved. Please speak it again after resuming.",
          );
        stopCapture();
        pending = true;
        setBusy(true);
        void post<Session>(
          `/api/interviews/${id}/${resume ? "resume" : "pause"}`,
        )
          .then((result) => {
            if (live) {
              apply(result);
              if (result.status === "active") speak(result.question);
            }
          })
          .catch(async (e) => {
            if (live) {
              setError(errorText(e));
              await recover();
            }
          })
          .finally(() => {
            pending = false;
            if (live) setBusy(false);
          });
      },
      finish() {
        void finish();
      },
      recover() {
        void recover();
      },
      help(action) {
        if (!recognition) {
          setError("");
          void send("", action);
        }
      },
      leave() {
        if (current && current.status !== "completed") return;
        stopCapture();
        stopCamera();
        store("interview-id", null);
        store("interview-partial", null);
        onBackRef.current();
      },
      again() {
        if (current?.status !== "completed") return;
        current = null;
        setSession(null);
        setError("");
        store("interview-id", null);
        store("interview-partial", null);
        setMicChecked(false);
        setSpeakerChecked(false);
        updateMode("ready");
        setConnection("Connection: ready");
      },
    };
    const online = () => {
      if (restoring) void recover();
    };
    const offline = () => {
      if (current?.status !== "completed") void recover();
    };
    const hide = () => {
      stopCapture();
      stopCamera();
      clearInterval(clock);
      clearTimeout(poll);
    };
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    window.addEventListener("pagehide", hide);
    void recover();
    return () => {
      live = false;
      hide();
      actions.current = initialActions;
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
      window.removeEventListener("pagehide", hide);
    };
  }, [preparation.id]);

  useEffect(() => {
    const list = transcript.current;
    if (list && list.scrollHeight - list.scrollTop - list.clientHeight < 200)
      list.scrollTop = list.scrollHeight;
  }, [session?.turns.length]);
  const completed = session?.status === "completed";
  const active = session?.status === "active";
  const disabled = !active || busy || recovering || mode === "listening";
  const title = completed
    ? "A conversation worth revisiting."
    : session
      ? "One question. Your perspective."
      : "Make yourself comfortable.";

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-5">
        <div>
          {(!session || completed) && (
            <button
              className="mb-5 flex min-h-8 items-center gap-2 text-xs text-zinc-500 hover:text-accent"
              onClick={() => actions.current.leave()}
            >
              <ArrowLeftIcon /> Back to preparation
            </button>
          )}
          <p className="eyebrow mb-3">
            {completed
              ? "03 / REFLECT"
              : session
                ? "03 / THE CONVERSATION"
                : "02 / AUDIO CHECK"}
          </p>
          <h1 className="text-3xl font-medium tracking-[-.045em] md:text-4xl">
            {title}
          </h1>
          <p className="mt-3 text-sm text-zinc-500">
            {preparation.target_role}{" "}
            <span className="mx-2 text-zinc-300">/</span>{" "}
            <span className="capitalize">
              {preparation.experience_level.replaceAll("-", " ")}
            </span>
          </p>
        </div>
        {session && !completed && (
          <div className="flex items-center gap-3 rounded-2xl border border-zinc-200 bg-white px-5 py-4">
            <ClockIcon className="text-zinc-400" />
            <span
              className="font-mono text-xl tracking-tight"
              aria-label="Time remaining"
            >
              {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
            </span>
            <span className="text-xs text-zinc-400">remaining</span>
          </div>
        )}
      </div>
      {error && (
        <p
          id="interview-error"
          role="alert"
          className="mb-6 rounded-2xl border border-zinc-300 bg-white p-5 text-sm leading-6"
        >
          {error}
        </p>
      )}
      {recovering && (
        <div className="mb-6 flex flex-wrap items-center gap-4 rounded-xl bg-zinc-100 p-4 text-sm">
          <span>Checking your saved conversation before continuing.</span>
          <button
            id="recover-interview"
            className="button-secondary"
            onClick={() => actions.current.recover()}
          >
            <ReloadIcon /> Recover connection
          </button>
        </div>
      )}
      <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="surface min-w-0 overflow-hidden">
          <div className="flex items-center justify-between gap-4 border-b border-zinc-100 px-6 py-5 md:px-8">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              {session ? <ChatBubbleIcon /> : <SpeakerLoudIcon />}
              {session
                ? completed
                  ? "Session transcript"
                  : "The conversation"
                : "Audio & connection"}
            </h2>
            <span className="text-[10px] uppercase tracking-wider text-zinc-400">
              {session ? "RESUME-LED PRACTICE" : "BEFORE YOU BEGIN"}
            </span>
          </div>
          {session ? (
            <div className="p-6 md:p-8">
              <p
                id="interview-state"
                role="status"
                className="mb-6 text-sm text-accent"
              >
                {state}
              </p>
              <ol
                id="transcript"
                ref={transcript}
                data-interview-id={session.id}
                aria-label="Saved interview transcript"
                aria-live="polite"
                aria-relevant="additions"
                tabIndex={0}
                className="max-h-[55dvh] space-y-7 overflow-y-auto pr-3 outline-none"
              >
                {session.turns.map((turn, index) => (
                  <li
                    key={index}
                    className={
                      turn.speaker === "Candidate"
                        ? "rounded-2xl bg-zinc-50 p-5"
                        : "px-1"
                    }
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <span className="eyebrow">
                        {turn.speaker === "Candidate" ? "You" : "Interviewer"}
                      </span>
                      {turn.assistance && (
                        <span className="rounded-full bg-[#e9efea] px-2 py-1 text-[10px] text-accent">
                          Hint · assisted
                        </span>
                      )}
                      {turn.action && (
                        <span className="text-[10px] text-zinc-400">
                          Conversation request
                        </span>
                      )}
                    </div>
                    <p className="whitespace-pre-wrap break-words text-[15px] leading-7">
                      {turn.text}
                    </p>
                  </li>
                ))}
              </ol>
              {busy && (
                <div aria-label="Preparing response" className="mt-6 space-y-2">
                  <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-100" />
                  <div className="h-3 w-1/2 animate-pulse rounded bg-zinc-100" />
                </div>
              )}
              <p className="mt-7 border-t border-zinc-100 pt-4 text-[11px] leading-5 text-zinc-400">
                {completed
                  ? "Your answers and requested assistance. No automated score."
                  : "Saved turns appear here. Speech recognition may contain mistakes."}
              </p>
            </div>
          ) : (
            <div className="p-6 md:p-8">
              <p className="mb-7 max-w-lg text-sm leading-7 text-zinc-500">
                A quiet space. A pair of headphones. A moment to gather your
                thoughts. You decide when the conversation begins.
              </p>
              {!supported && (
                <p
                  role="alert"
                  className="mb-5 rounded-xl bg-zinc-100 p-4 text-sm"
                >
                  This browser does not support spoken interviews. Open this
                  workspace in Chrome or Edge.
                </p>
              )}
              <div className="divide-y divide-zinc-100">
                <div className="flex flex-wrap items-center justify-between gap-4 py-5">
                  <div>
                    <h3 className="text-sm font-medium">Microphone</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      Check the live level, then stop the check.
                    </p>
                  </div>
                  <button
                    id="mic-check"
                    className="button-secondary"
                    onClick={() => actions.current.mic()}
                    disabled={busy}
                  >
                    {capture.includes(": on")
                      ? "Stop microphone check"
                      : "Check microphone"}
                    {micChecked && <CheckIcon className="text-accent" />}
                  </button>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-4 py-5">
                  <div>
                    <h3 className="text-sm font-medium">Speaker</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      Play a short sample through your headphones.
                    </p>
                  </div>
                  <button
                    id="speaker-check"
                    className="button-secondary"
                    onClick={() => actions.current.speaker()}
                    disabled={busy}
                  >
                    <SpeakerLoudIcon /> Test speaker
                  </button>
                </div>
              </div>
              {speakerChecked && (
                <p
                  role="status"
                  className="mt-2 text-xs leading-5 text-zinc-500"
                >
                  If you did not hear the sample, check your audio output and
                  test again.
                </p>
              )}
              <div className="mt-8 rounded-2xl bg-zinc-50 p-5">
                <p className="text-xs font-medium">A note before you start</p>
                <p className="mt-2 text-xs leading-6 text-zinc-500">
                  OpenAI needs a configured API key and separate API billing. A
                  ChatGPT subscription does not include API access. Provider
                  availability is checked when you start.
                </p>
              </div>
              <div className="mt-7 flex flex-wrap items-center justify-between gap-4">
                <p className="text-xs text-zinc-500">
                  Up to 10 minutes. Pause anytime.
                </p>
                <button
                  id="start-interview"
                  className="button"
                  onClick={() => actions.current.start()}
                  disabled={busy || recovering || !supported}
                >
                  {busy
                    ? "Preparing your first question…"
                    : "Start 10-minute interview"}
                  <ArrowRightIcon />
                </button>
              </div>
            </div>
          )}
        </section>
        <aside className="space-y-5">
          <div className="rounded-[2rem] bg-[#e9efea] px-7 py-8 text-center">
            <p className="eyebrow text-accent">
              {completed
                ? "PRACTICE COMPLETE"
                : session
                  ? "YOUR INTERVIEWER"
                  : "READY FOR YOUR NEXT CHAPTER"}
            </p>
            <div className="my-6 text-accent">
              <VoiceMark
                large
                active={
                  mode === "speaking" ||
                  mode === "listening" ||
                  mode === "thinking"
                }
              />
            </div>
            <h2 className="text-xl font-medium tracking-tight">
              {completed
                ? "A little clearer, each time."
                : session
                  ? mode === "listening"
                    ? "The floor is yours."
                    : "Room to find your words."
                  : "This is your practice space."}
            </h2>
            <p className="mx-auto mt-3 max-w-60 text-xs leading-6 text-[#637269]">
              {completed
                ? "Read your answers. Notice what you would explain differently. Then try again."
                : "No perfect answers required. Take your time, ask for a hint, or pause whenever you need."}
            </p>
          </div>
          <section
            className={
              completed
                ? "hidden"
                : "rounded-2xl border border-zinc-200 bg-white p-5"
            }
            aria-label="Optional camera preview"
          >
            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
              <VideoIcon />
              <h2>Camera preview</h2>
              <span className="ml-auto text-[10px] font-normal text-zinc-400">
                OPTIONAL
              </span>
            </div>
            <video
              ref={video}
              id="camera-preview"
              autoPlay
              muted
              playsInline
              hidden={!cameraOn}
              aria-label="Local camera preview"
              className="mb-3 w-full rounded-xl"
            />
            <p
              id="camera-state"
              role="status"
              className="mb-3 text-xs leading-5 text-zinc-500"
            >
              {cameraState}
            </p>
            <button
              id="camera-toggle"
              className="button-secondary w-full"
              aria-pressed={cameraOn}
              onClick={() => actions.current.camera()}
            >
              {cameraOn || cameraPending
                ? "Disable camera preview"
                : "Enable camera preview"}
            </button>
            <p className="mt-3 text-[10px] leading-5 text-zinc-400">
              Local preview only. Never recorded or assessed.
            </p>
          </section>
          <div className={completed ? "hidden" : "px-1"}>
            <p
              id="capture-state"
              role="status"
              className="mb-2 text-[11px] text-zinc-500"
            >
              {capture}
            </p>
            <label htmlFor="mic-level" className="sr-only">
              Microphone level
            </label>
            <progress ref={meter} id="mic-level" max={100} defaultValue={0} />
            <p
              id="connection-state"
              role="status"
              className="mt-3 text-[10px] text-zinc-400"
            >
              {connection}
            </p>
          </div>
        </aside>
      </div>
      {session && !completed && (
        <div className="sticky bottom-3 mt-7 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-200 bg-white p-4 shadow-[0_8px_30px_-12px_rgba(30,40,35,0.15)]">
          <div className="flex flex-wrap gap-2">
            <button
              id="answer-button"
              className="button"
              disabled={disabled}
              onClick={() => actions.current.answer()}
            >
              <PlayIcon />
              {mode === "listening"
                ? "Listening…"
                : busy
                  ? "Thinking…"
                  : "Speak answer"}
            </button>
            <button
              id="stop-playback"
              className="button-secondary"
              onClick={() => actions.current.interrupt()}
              disabled={!active}
            >
              Interrupt playback
            </button>
            <details className="relative">
              <summary className="button-secondary">Ask for help</summary>
              <div className="absolute bottom-full left-0 mb-3 w-60 rounded-2xl border border-zinc-200 bg-white p-3 shadow-lg">
                {[
                  ["repeat", "Repeat question"],
                  ["rephrase", "Rephrase question"],
                  ["think", "Need thinking time"],
                  ["hint", "Request a hint"],
                ].map(([action, label]) => (
                  <button
                    key={action}
                    className="interview-action block min-h-11 w-full rounded-lg px-3 text-left text-xs hover:bg-zinc-50"
                    data-action={action}
                    disabled={disabled}
                    onClick={(event) => {
                      event.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      actions.current.help(action);
                    }}
                  >
                    {label}
                  </button>
                ))}
                <p className="px-3 pt-2 text-[10px] leading-5 text-zinc-400">
                  Thinking time keeps the clock running. Pause stops it.
                </p>
              </div>
            </details>
          </div>
          <div className="flex gap-2">
            <button
              id="pause-interview"
              className="button-secondary"
              disabled={busy || recovering}
              onClick={() => actions.current.pause()}
            >
              {session.status === "paused" ? <PlayIcon /> : <PauseIcon />}
              {session.status === "paused"
                ? "Resume interview"
                : "Pause interview"}
            </button>
            <button
              id="finish-interview"
              className="button-danger"
              disabled={busy && mode !== "thinking"}
              onClick={() => actions.current.finish()}
            >
              <StopIcon /> Finish interview
            </button>
          </div>
        </div>
      )}
      {completed && (
        <div className="mt-7 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white p-6">
          <div>
            <p className="text-sm font-medium">
              Keep the context. Try a fresh conversation.
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Your saved preparation is ready when you are.
            </p>
          </div>
          <MagneticButton onClick={() => actions.current.again()}>
            Practice again <ArrowRightIcon />
          </MagneticButton>
        </div>
      )}
      <details className="mt-7 max-w-2xl text-xs text-zinc-500">
        <summary className="flex min-h-8 items-center gap-2">
          <LockClosedIcon /> What is shared when I start?
        </summary>
        <p className="mt-3 leading-6">
          OpenAI receives your saved resume context and completed text answers.
          Browser speech recognition may send microphone audio to its platform
          service. This app does not store raw audio or video. Local data
          remains until deleted; provider retention is separate.
        </p>
      </details>
    </div>
  );
}
