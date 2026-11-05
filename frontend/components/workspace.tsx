"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowRightIcon,
  CheckIcon,
  FileTextIcon,
  LockClosedIcon,
  PlusIcon,
  UploadIcon,
  TrashIcon,
  Pencil1Icon,
  ArrowTopRightIcon,
  SpeakerLoudIcon,
} from "@radix-ui/react-icons";
import {
  api,
  errorText,
  storedInterviewId,
  type Preparation,
  type PreparationInput,
  type PreparationSummary,
} from "../lib/api";
import InterviewStudio from "./interview-studio";
import { MagneticButton, VoiceMark } from "./motion";

const empty: PreparationInput = {
  target_role: "",
  experience_level: "",
  resume_text: "",
  job_description: "",
};
const levels = [
  ["entry", "Entry-level"],
  ["early-career", "Early-career"],
  ["mid-level", "Mid-level"],
  ["senior", "Senior"],
  ["staff", "Staff or leadership"],
];
const inputOf = (p: Preparation): PreparationInput => ({
  target_role: p.target_role,
  experience_level: p.experience_level,
  resume_text: p.resume_text,
  job_description: p.job_description,
});

export default function Workspace() {
  const [fields, setFields] = useState<PreparationInput>(empty);
  const [saved, setSaved] = useState<Preparation | null>(null);
  const [records, setRecords] = useState<PreparationSummary[]>([]);
  const [studio, setStudio] = useState(false);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [fileName, setFileName] = useState("");
  const uploadVersion = useRef(0);
  const form = useRef<HTMLFormElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const guardedAction = useRef<(() => void) | null>(null);
  const reduced = useReducedMotion();
  const dirty =
    JSON.stringify(fields) !== JSON.stringify(saved ? inputOf(saved) : empty);

  async function load() {
    setLoading(true);
    try {
      setRecords(await api<PreparationSummary[]>("/api/preparations"));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    let cancelled = false;
    async function restore() {
      try {
        const draft = sessionStorage.getItem("preparation-draft");
        if (draft) {
          const data = JSON.parse(draft);
          if (data.fields && typeof data.fields.resume_text === "string") {
            setFields({ ...empty, ...data.fields });
            if (data.saved && data.id) setSaved({ ...data.saved, id: data.id });
            if (data.view === "devices" && data.saved && data.id)
              setStudio(true);
          }
        }
        const id = storedInterviewId();
        if (id) {
          const session = await api<{ preparation_id: string }>(
            `/api/interviews/${encodeURIComponent(id)}`,
          );
          const prep = await api<Preparation>(
            `/api/preparations/${session.preparation_id}`,
          );
          if (!cancelled) {
            setSaved(prep);
            setFields(inputOf(prep));
            setStudio(true);
          }
        }
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      } finally {
        if (!cancelled) setReady(true);
      }
    }
    void restore();
    void load();
    return () => {
      cancelled = true;
      uploadVersion.current++;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    try {
      sessionStorage.setItem(
        "preparation-draft",
        JSON.stringify({
          id: saved?.id,
          saved,
          fields,
          view: studio ? "devices" : "prepare",
        }),
      );
    } catch {
      setStatus(
        "Browser storage is unavailable. Keep this tab open to preserve your draft.",
      );
    }
  }, [ready, fields, saved, studio]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function guard(action: () => void) {
    if (!dirty) return action();
    guardedAction.current = action;
    dialog.current?.showModal();
  }
  function fill(prep: Preparation | null) {
    uploadVersion.current++;
    setExtracting(false);
    setFileName("");
    setSaved(prep);
    setFields(prep ? inputOf(prep) : empty);
    setError("");
  }
  function change(key: keyof PreparationInput, value: string) {
    setFields((previous) => ({ ...previous, [key]: value }));
    setStatus("");
  }
  async function save(event?: FormEvent): Promise<Preparation | null> {
    event?.preventDefault();
    if (saving || opening || extracting || !form.current?.reportValidity())
      return null;
    if (!fields.resume_text.trim() || !fields.target_role.trim()) {
      setError("Enter your resume text and target role before saving.");
      return null;
    }
    setSaving(true);
    setError("");
    try {
      const prep = await api<Preparation>(
        saved ? `/api/preparations/${saved.id}` : "/api/preparations",
        {
          method: saved ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fields),
        },
      );
      setSaved(prep);
      setFields(inputOf(prep));
      setStatus("Preparation saved.");
      await load();
      return prep;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setSaving(false);
    }
  }
  async function upload(file?: File) {
    const version = ++uploadVersion.current;
    if (!file) return;
    setError("");
    if (
      !file.name.toLowerCase().endsWith(".pdf") ||
      (file.type && file.type !== "application/pdf")
    ) {
      setError("Choose a PDF file, or paste your resume text below.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError("This PDF is larger than 8 MB. Choose a smaller file.");
      return;
    }
    setExtracting(true);
    setFileName(file.name);
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await api<{ resume_text: string }>("/api/extract", {
        method: "POST",
        body,
      });
      if (version === uploadVersion.current) {
        change("resume_text", result.resume_text);
        setStatus(
          "Text extracted. Review names, dates, and bullet points before saving.",
        );
      }
    } catch (e) {
      if (version === uploadVersion.current) setError(errorText(e));
    } finally {
      if (version === uploadVersion.current) setExtracting(false);
    }
  }
  function open(record: PreparationSummary, practise = false) {
    guard(() => {
      void (async () => {
        setOpening(true);
        try {
          const prep = await api<Preparation>(`/api/preparations/${record.id}`);
          fill(prep);
          setStatus("Saved preparation opened.");
          setStudio(practise);
          if (!practise) document.getElementById("target-role")?.focus();
        } catch (e) {
          setError(errorText(e));
        } finally {
          setOpening(false);
        }
      })();
    });
  }
  async function remove(record: PreparationSummary) {
    if (
      !confirm(
        `Delete ${record.target_role} and its interview history from this device? This cannot be undone.`,
      )
    )
      return;
    try {
      await api(`/api/preparations/${record.id}`, { method: "DELETE" });
      if (saved?.id === record.id) fill(null);
      await load();
      setStatus("Preparation deleted from this device.");
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="min-h-dvh">
      <header className="border-b border-zinc-200/80 bg-white/80">
        <div className="mx-auto flex min-h-20 max-w-[1400px] items-center justify-between gap-4 px-5 md:px-10">
          <div className="flex items-center gap-3 text-lg font-semibold tracking-[-.045em]">
            <span className="flex size-9 items-center justify-center rounded-xl bg-accent text-white">
              <VoiceMark />
            </span>
            InterviewDaddy
            <span className="ml-1 hidden rounded-md border border-zinc-200 px-1.5 py-1 font-mono text-[9px] tracking-wide text-zinc-400 sm:inline">
              LOCAL
            </span>
          </div>
          <div className="flex items-center gap-5">
            <span className="hidden text-xs text-zinc-500 sm:flex sm:items-center sm:gap-2">
              <LockClosedIcon /> Your private practice space
            </span>
            <span className="flex size-9 items-center justify-center rounded-full border border-zinc-200 bg-zinc-50 text-accent">
              <FileTextIcon />
            </span>
          </div>
        </div>
      </header>
      <main
        id="main-content"
        className="mx-auto max-w-[1400px] px-5 py-8 outline-none md:px-10 md:py-12"
        tabIndex={-1}
      >
        <AnimatePresence mode="wait" initial={false}>
          {studio && saved ? (
            <motion.div
              key="studio"
              initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <InterviewStudio
                preparation={saved}
                onBack={() => {
                  setStudio(false);
                  setStatus("");
                }}
              />
            </motion.div>
          ) : (
            <motion.div
              key="prepare"
              initial={false}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="mb-10 grid items-end gap-6 md:grid-cols-[1fr_auto]">
                <div>
                  <p className="eyebrow mb-4 flex items-center gap-2">
                    <span className="size-1.5 rounded-full bg-accent" /> THE
                    PRACTICE ROOM
                  </p>
                  <h1 className="max-w-2xl text-4xl font-medium leading-[1.08] tracking-[-.055em] md:text-[3.5rem]">
                    Good answers start
                    <br className="hidden sm:block" /> with{" "}
                    <span className="text-accent">your experience.</span>
                  </h1>
                  <p className="mt-5 max-w-lg text-sm leading-7 text-zinc-500">
                    Bring the work you know. Find the words to explain it.
                    <br className="hidden sm:block" /> A focused conversation,
                    built around your next role.
                  </p>
                </div>
                <div className="hidden items-center gap-4 pb-1 md:flex">
                  <span className="font-mono text-3xl font-light tracking-tighter text-zinc-300">
                    01<span className="mx-2 text-lg">/</span>03
                  </span>
                  <div className="text-xs leading-5">
                    <span className="block font-medium">Your preparation</span>
                    <span className="text-zinc-400">Next: audio check</span>
                  </div>
                </div>
              </div>
              <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_320px] xl:gap-12">
                <div className="surface min-w-0 overflow-hidden">
                  <div className="flex items-center justify-between gap-3 border-b border-zinc-100 px-6 py-5 md:px-8">
                    <div className="flex items-center gap-3">
                      <span className="flex size-8 items-center justify-center rounded-lg bg-[#edf3ef] text-accent">
                        <FileTextIcon />
                      </span>
                      <h2 className="text-sm font-semibold">
                        {saved
                          ? "Your session brief"
                          : "A little context goes a long way"}
                      </h2>
                    </div>
                    <span
                      id="save-note"
                      className="hidden text-xs text-zinc-400 sm:block"
                    >
                      {dirty
                        ? "Unsaved changes"
                        : saved
                          ? "Saved on this device"
                          : "Start here"}
                    </span>
                  </div>
                  <form ref={form} onSubmit={save} className="p-6 md:p-8">
                    {error && (
                      <div
                        id="error-message"
                        role="alert"
                        className="mb-6 rounded-xl border border-zinc-300 bg-zinc-50 p-4 text-sm leading-6"
                      >
                        {error}
                        <button
                          type="button"
                          className="ml-3 underline underline-offset-4"
                          onClick={() => {
                            setError("");
                            void load();
                          }}
                        >
                          Retry connection
                        </button>
                      </div>
                    )}
                    <p
                      id="status-message"
                      role="status"
                      className={
                        status ? "mb-5 text-sm text-accent" : "sr-only"
                      }
                    >
                      {status}
                    </p>
                    <fieldset
                      disabled={opening || saving || !ready}
                      aria-busy={opening || saving}
                      className="min-w-0"
                    >
                      <div className="mb-6 flex items-start justify-between gap-4">
                        <div>
                          <p className="eyebrow mb-2">01 / YOUR EXPERIENCE</p>
                          <h3 className="text-xl font-medium tracking-tight">
                            Start with your resume.
                          </h3>
                        </div>
                        <span className="rounded-full bg-zinc-50 px-3 py-1.5 text-[10px] text-zinc-500">
                          PDF or plain text
                        </span>
                      </div>
                      <label className="group relative mb-5 flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/70 px-4 py-7 text-center transition-colors hover:border-accent hover:bg-[#f3f7f4] focus-within:outline-2 focus-within:outline-accent">
                        <input
                          id="resume-file"
                          aria-label="Resume PDF"
                          type="file"
                          accept="application/pdf,.pdf"
                          disabled={extracting || saving}
                          onChange={(event) =>
                            void upload(event.target.files?.[0])
                          }
                          className="absolute inset-0 size-full cursor-pointer opacity-0"
                        />
                        <span className="flex size-10 items-center justify-center rounded-xl border border-zinc-200 bg-white text-accent">
                          <UploadIcon className="size-5" />
                        </span>
                        <span className="text-sm font-medium">
                          {extracting
                            ? "Reading your resume…"
                            : fileName || "Choose a resume PDF"}
                        </span>
                        <span className="text-xs text-zinc-500">
                          Text-based PDF, up to 8 MB. You can also paste below.
                        </span>
                      </label>
                      <div className="field">
                        <label htmlFor="resume-text">
                          Extracted resume text
                        </label>
                        <textarea
                          id="resume-text"
                          className="input min-h-40 resize-y text-sm leading-6"
                          value={fields.resume_text}
                          onChange={(e) =>
                            change("resume_text", e.target.value)
                          }
                          maxLength={100000}
                          required
                          disabled={extracting}
                          placeholder="Paste your experience here, or review the text from your PDF."
                          aria-describedby="resume-hint"
                        />
                        <p
                          id="resume-hint"
                          className="text-xs leading-5 text-zinc-500"
                        >
                          Check names, dates, and achievements. This is what
                          your interviewer will draw on.
                        </p>
                      </div>
                      <div className="my-8 border-t border-zinc-100" />
                      <p className="eyebrow mb-2">02 / YOUR NEXT ROLE</p>
                      <h3 className="mb-6 text-xl font-medium tracking-tight">
                        Give the conversation direction.
                      </h3>
                      <div className="grid gap-5 sm:grid-cols-[1.25fr_1fr]">
                        <div className="field">
                          <label htmlFor="target-role">Target role</label>
                          <input
                            id="target-role"
                            className="input"
                            value={fields.target_role}
                            onChange={(e) =>
                              change("target_role", e.target.value)
                            }
                            maxLength={120}
                            required
                            autoComplete="organization-title"
                            placeholder="e.g. Backend Engineer"
                          />
                        </div>
                        <div className="field">
                          <label htmlFor="experience-level">
                            Experience level
                          </label>
                          <select
                            id="experience-level"
                            className="input"
                            value={fields.experience_level}
                            onChange={(e) =>
                              change("experience_level", e.target.value)
                            }
                            required
                          >
                            <option value="">Choose your level</option>
                            {levels.map(([value, label]) => (
                              <option key={value} value={value}>
                                {label}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="field mt-5">
                        <label htmlFor="job-description">
                          Job description{" "}
                          <span className="font-normal text-zinc-400">
                            (optional)
                          </span>
                        </label>
                        <textarea
                          id="job-description"
                          className="input min-h-24 resize-y text-sm leading-6"
                          value={fields.job_description}
                          onChange={(e) =>
                            change("job_description", e.target.value)
                          }
                          maxLength={30000}
                          rows={3}
                          placeholder="Paste the role description for a more relevant conversation."
                        />
                      </div>
                      <div className="mt-8 flex flex-wrap items-center justify-between gap-4 border-t border-zinc-100 pt-6">
                        <p className="flex items-center gap-2 text-[11px] text-zinc-500">
                          <LockClosedIcon /> Saved locally. No account needed.
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <button
                            id="save-button"
                            className="button-secondary"
                            disabled={saving || extracting || !ready}
                            type="submit"
                          >
                            {saving ? "Saving…" : "Save preparation"}
                          </button>
                          <MagneticButton
                            disabled={saving || extracting || !ready}
                            onClick={() => {
                              void (async () => {
                                const prep =
                                  dirty || !saved ? await save() : saved;
                                if (prep) {
                                  setStudio(true);
                                  window.scrollTo(0, 0);
                                }
                              })();
                            }}
                          >
                            Continue to audio <ArrowRightIcon />
                          </MagneticButton>
                        </div>
                      </div>
                    </fieldset>
                  </form>
                </div>
                <aside className="min-w-0 space-y-8 lg:pt-1">
                  <section className="rounded-[2rem] bg-[#e9efea] p-7">
                    <div className="mb-6 flex items-center justify-between">
                      <p className="eyebrow text-accent">
                        A REHEARSAL, NOT A VERDICT
                      </p>
                      <SpeakerLoudIcon className="text-accent" />
                    </div>
                    <h2 className="text-2xl font-medium leading-tight tracking-[-.04em]">
                      Your work.
                      <br />
                      In your own words.
                    </h2>
                    <div className="my-5 flex items-center gap-4 border-y border-[#d7e0d9] py-5">
                      <div className="text-accent">
                        <VoiceMark active />
                      </div>
                      <p className="text-xs leading-5 text-[#526257]">
                        One question at a time.
                        <br />
                        Space to pause and think.
                      </p>
                    </div>
                    <ol className="space-y-4">
                      {[
                        [
                          "01",
                          "Set the context",
                          "Your resume and the role ahead.",
                        ],
                        [
                          "02",
                          "Check your audio",
                          "Get comfortable before you start.",
                        ],
                        [
                          "03",
                          "Talk it through",
                          "Up to 10 minutes. Review your transcript.",
                        ],
                      ].map(([number, title, detail]) => (
                        <li key={number} className="flex gap-3">
                          <span className="pt-0.5 font-mono text-[10px] text-accent">
                            {number}
                          </span>
                          <div>
                            <p className="text-xs font-medium">{title}</p>
                            <p className="mt-1 text-xs leading-5 text-[#627168]">
                              {detail}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>
                  <section aria-labelledby="saved-title">
                    <div className="mb-4 flex items-center justify-between">
                      <h2 id="saved-title" className="text-sm font-semibold">
                        Saved preparations
                      </h2>
                      <button
                        type="button"
                        title="New preparation"
                        aria-label="New preparation"
                        className="flex size-10 items-center justify-center rounded-full border border-zinc-200 bg-white text-accent hover:bg-zinc-50"
                        onClick={() =>
                          guard(() => {
                            fill(null);
                            setStatus("");
                            document.getElementById("target-role")?.focus();
                          })
                        }
                      >
                        <PlusIcon />
                      </button>
                    </div>
                    {loading ? (
                      <div
                        aria-label="Loading saved preparations"
                        className="space-y-3"
                      >
                        {[0, 1].map((i) => (
                          <div
                            key={i}
                            className="h-20 animate-pulse rounded-xl bg-zinc-200/70"
                          />
                        ))}
                      </div>
                    ) : records.length ? (
                      <ul
                        id="saved-list"
                        aria-label="Saved preparations"
                        className="divide-y divide-zinc-200"
                      >
                        {records.map((record, index) => (
                          <motion.li
                            key={record.id}
                            layout="position"
                            initial={{ opacity: reduced ? 1 : 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: reduced ? 0 : index * 0.06 }}
                            className="py-5 first:pt-1"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <h3 className="break-words text-sm font-medium">
                                  {record.target_role}
                                </h3>
                                <p className="mt-1.5 text-[11px] capitalize text-zinc-500">
                                  {record.experience_level.replaceAll("-", " ")}{" "}
                                  <span className="mx-1">·</span>{" "}
                                  {new Date(
                                    record.updated_at,
                                  ).toLocaleDateString(undefined, {
                                    month: "short",
                                    day: "numeric",
                                  })}
                                </p>
                              </div>
                              <button
                                className="flex size-9 shrink-0 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800"
                                aria-label={`Delete preparation: ${record.target_role}`}
                                onClick={() => void remove(record)}
                              >
                                <TrashIcon />
                              </button>
                            </div>
                            <div className="mt-3 flex items-center gap-4">
                              <button
                                className="flex min-h-9 items-center gap-1.5 text-xs font-medium text-accent"
                                onClick={() => open(record, true)}
                              >
                                Practise <ArrowTopRightIcon />
                              </button>
                              <button
                                className="flex min-h-9 items-center gap-1.5 text-xs text-zinc-500"
                                aria-label={`Open preparation: ${record.target_role}`}
                                onClick={() => open(record)}
                              >
                                <Pencil1Icon /> Open preparation
                              </button>
                            </div>
                          </motion.li>
                        ))}
                      </ul>
                    ) : (
                      <div
                        id="empty-saved"
                        className="rounded-2xl border border-dashed border-zinc-300 px-5 py-6"
                      >
                        <FileTextIcon className="mb-3 size-5 text-zinc-400" />
                        <p className="text-sm font-medium">
                          Your next chapter starts here.
                        </p>
                        <p className="mt-2 text-xs leading-6 text-zinc-500">
                          Save your first preparation. Come back to it whenever
                          you want to practise.
                        </p>
                      </div>
                    )}
                  </section>
                  <details className="border-t border-zinc-200 pt-5 text-xs text-zinc-500">
                    <summary className="flex min-h-8 items-center gap-2">
                      <LockClosedIcon /> What stays private?
                    </summary>
                    <p className="mt-3 leading-6">
                      Your resume and job description stay in local SQLite until
                      deleted. Starting an interview shares this context and
                      completed answers with OpenAI. Browser speech recognition
                      may send audio to its platform service. This app stores no
                      raw audio or video. Provider retention is separate.
                    </p>
                  </details>
                </aside>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>
      <footer className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-5 py-8 text-[11px] text-zinc-400 md:px-10">
        <span>Less pressure. More practice.</span>
        <span>
          Local workspace <span className="mx-2">/</span> No automated scores
        </span>
      </footer>
      <dialog
        ref={dialog}
        className="fixed inset-0 m-auto w-[min(440px,calc(100%-32px))] rounded-3xl border border-zinc-200 p-7 shadow-xl backdrop:bg-zinc-900/30"
        onCancel={() => {
          guardedAction.current = null;
        }}
      >
        <h2 className="text-xl font-medium tracking-tight">
          Keep your changes?
        </h2>
        <p className="mt-3 text-sm leading-6 text-zinc-500">
          Save this preparation before switching, or discard your edits.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <button
            className="button"
            onClick={() => {
              dialog.current?.close();
              void save().then((result) => {
                if (result) guardedAction.current?.();
                guardedAction.current = null;
              });
            }}
          >
            <CheckIcon /> Save changes
          </button>
          <button
            className="button-secondary"
            onClick={() => {
              dialog.current?.close();
              guardedAction.current?.();
              guardedAction.current = null;
            }}
          >
            Discard changes
          </button>
          <button
            className="button-secondary"
            onClick={() => {
              dialog.current?.close();
              guardedAction.current = null;
            }}
          >
            Cancel
          </button>
        </div>
      </dialog>
    </div>
  );
}
