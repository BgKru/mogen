import { describe, expect, it } from "vitest";

import { ApiError, fieldErrorsFrom, toApiError, userMessageFor } from "./errors";

describe("toApiError", () => {
  it("returns an existing ApiError unchanged", () => {
    const error = new ApiError({ status: 404, code: "PROJECT_NOT_FOUND", message: "missing" });
    expect(toApiError(error)).toBe(error);
  });

  it("wraps an unknown error", () => {
    const error = toApiError(new Error("boom"));
    expect(error.status).toBe(0);
    expect(error.code).toBe("UNKNOWN_ERROR");
  });

  it("parses the backend error envelope", () => {
    const error = toApiError({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          error: {
            code: "VALIDATION_ERROR",
            message: "The request is invalid.",
            details: [{ field: "name", code: "MISSING", message: "Field required" }],
            request_id: "request-1",
          },
        },
      },
    });

    expect(error.status).toBe(422);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.requestId).toBe("request-1");
    expect(error.details).toEqual([{ field: "name", code: "MISSING", message: "Field required" }]);
  });
});

describe("userMessageFor", () => {
  it("maps a known error code", () => {
    expect(
      userMessageFor(new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "" })),
    ).toBe("Неверный email или пароль.");
  });

  it("maps a network failure", () => {
    expect(userMessageFor(new ApiError({ status: 0, code: "NETWORK_ERROR", message: "" }))).toBe(
      "Нет соединения с сервером. Проверьте подключение и повторите попытку.",
    );
  });

  it("maps an unknown server failure", () => {
    expect(userMessageFor(new ApiError({ status: 503, code: "SOMETHING_ELSE", message: "" }))).toBe(
      "Сервер временно недоступен. Попробуйте позже.",
    );
  });
});

describe("fieldErrorsFrom", () => {
  it("maps server field details onto form messages", () => {
    const error = new ApiError({
      status: 422,
      code: "VALIDATION_ERROR",
      message: "invalid",
      details: [
        { field: "email", code: "MISSING", message: "Field required" },
        { field: "password", code: null, message: "Password is invalid" },
      ],
    });

    expect(fieldErrorsFrom(error)).toEqual({
      email: "Обязательное поле.",
      password: "Password is invalid",
    });
  });

  it("ignores details without a field", () => {
    const error = new ApiError({
      status: 422,
      code: "VALIDATION_ERROR",
      message: "invalid",
      details: [{ field: null, code: "MISSING", message: "Field required" }],
    });

    expect(fieldErrorsFrom(error)).toEqual({});
  });
});
