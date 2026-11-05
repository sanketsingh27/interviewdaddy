export type Preparation = {
  id: string;
  target_role: string;
  experience_level: string;
  resume_text: string;
  job_description: string;
  created_at: string;
  updated_at: string;
};
export type PreparationSummary = Pick<
  Preparation,
  "id" | "target_role" | "experience_level" | "updated_at"
>;
export type PreparationInput = Pick<
  Preparation,
  "target_role" | "experience_level" | "resume_text" | "job_description"
>;

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (response.status === 204) return undefined as T;
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "The server could not be reached. Check that the Python API is running, then retry.",
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail
          .map(
            (item: { loc?: string[]; msg: string }) =>
              `${item.loc?.at(-1)?.replaceAll("_", " ") || "Field"}: ${item.msg}`,
          )
          .join(". ")
      : typeof detail === "string"
        ? detail
        : "The request failed. Please try again.";
    throw new Error(message);
  }
  return data;
}
export function post<T>(path: string, body?: unknown) {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}
export function storedInterviewId(): string | null {
  const value = sessionStorage.getItem("interview-id");
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}
export function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
