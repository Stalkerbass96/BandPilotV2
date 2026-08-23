interface FastApiIssue {
  message?: unknown;
}

interface FastApiDetail {
  message?: unknown;
  issues?: unknown;
  failed?: unknown;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Convert Axios/FastAPI errors, including structured validation errors, to UI-safe text. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const responseData = (
    error as { response?: { data?: { detail?: unknown; message?: unknown } } }
  )?.response?.data;
  const detail = responseData?.detail;

  const direct = nonEmptyString(detail) ?? nonEmptyString(responseData?.message);
  if (direct) return direct;

  if (detail && typeof detail === "object") {
    const structured = detail as FastApiDetail;
    const message = nonEmptyString(structured.message);
    const issues = Array.isArray(structured.issues)
      ? structured.issues
          .map((issue) => nonEmptyString((issue as FastApiIssue)?.message))
          .filter((item): item is string => item !== null)
      : [];
    if (message && issues.length > 0) {
      return `${message}: ${issues[0]}${issues.length > 1 ? ` (+${issues.length - 1} more)` : ""}`;
    }
    if (message) return message;
  }

  return nonEmptyString((error as { message?: unknown })?.message) ?? fallback;
}
