import { describe, expect, it } from "vitest";
import { apiErrorMessage } from "./apiError";

describe("apiErrorMessage", () => {
  it("returns a plain FastAPI detail", () => {
    expect(apiErrorMessage({ response: { data: { detail: "No repair result" } } }, "Fallback"))
      .toBe("No repair result");
  });

  it("formats professional validation errors without rendering an object", () => {
    const error = {
      response: {
        data: {
          detail: {
            message: "Score failed professional playability validation",
            issues: [
              { message: "String and fret do not reproduce the source pitch" },
              { message: "Chord contains a same-string collision" },
            ],
          },
        },
      },
    };
    expect(apiErrorMessage(error, "Fallback")).toBe(
      "Score failed professional playability validation: String and fret do not reproduce the source pitch (+1 more)",
    );
  });

  it("falls back to a normal Error message", () => {
    expect(apiErrorMessage(new Error("Network unavailable"), "Fallback"))
      .toBe("Network unavailable");
  });
});
