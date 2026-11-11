import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

import {
  BASE_URL,
  OBJECT_IMAGE,
  ORIGIN_HEADER,
  csrfToken,
  registerThroughApi,
  uniqueEmail,
} from "./helpers";

/**
 * Live authorization, CSRF and upload-validation matrix (roadmap 9.5).
 *
 * These cases drive the public HTTP interface with independent cookie jars, so
 * they prove isolation between two real users rather than mocked dependencies.
 * They never read or write another user's data beyond what the API exposes.
 */
test.describe("security matrix (9.5)", () => {
  test("two users are isolated from each other's projects and assets", async ({ playwright }) => {
    const alice = await playwright.request.newContext({ baseURL: BASE_URL });
    const bob = await playwright.request.newContext({ baseURL: BASE_URL });
    const anonymous = await playwright.request.newContext({ baseURL: BASE_URL });

    await registerThroughApi(alice, uniqueEmail("alice"));
    await registerThroughApi(bob, uniqueEmail("bob"));

    const createResponse = await alice.post("/api/v1/projects", {
      data: { name: "Alice private project", type: "OBJECT" },
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": await csrfToken(alice) },
    });
    expect(createResponse.status()).toBe(201);
    const projectId = (await createResponse.json()).id as string;

    expect((await bob.get(`/api/v1/projects/${projectId}`)).status()).toBe(404);
    expect((await bob.get(`/api/v1/projects/${projectId}/images`)).status()).toBe(404);
    expect((await bob.get(`/api/v1/projects/${projectId}/status`)).status()).toBe(404);
    expect((await bob.get(`/api/v1/projects/${projectId}/result`)).status()).toBe(404);
    expect((await bob.get(`/api/v1/projects/${projectId}/download`)).status()).toBe(404);

    expect((await anonymous.get(`/api/v1/projects/${projectId}`)).status()).toBe(401);
    expect((await anonymous.get(`/api/v1/projects/${projectId}/download`)).status()).toBe(401);

    await alice.delete(`/api/v1/projects/${projectId}`, {
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": await csrfToken(alice) },
    });
  });

  test("a state change without a CSRF token is rejected", async ({ playwright }) => {
    const context = await playwright.request.newContext({ baseURL: BASE_URL });
    await registerThroughApi(context, uniqueEmail("csrf"));

    const response = await context.post("/api/v1/projects", {
      data: { name: "No CSRF", type: "OBJECT" },
      headers: ORIGIN_HEADER,
    });

    expect(response.status()).toBe(403);
    expect((await response.json()).error.code).toBe("CSRF_VALIDATION_FAILED");
  });

  test("a CSRF token bound to another session cannot be used", async ({ playwright }) => {
    const alice = await playwright.request.newContext({ baseURL: BASE_URL });
    const bob = await playwright.request.newContext({ baseURL: BASE_URL });
    await registerThroughApi(alice, uniqueEmail("csrf-alice"));
    await registerThroughApi(bob, uniqueEmail("csrf-bob"));

    const aliceToken = await csrfToken(alice);
    const response = await bob.post("/api/v1/projects", {
      data: { name: "Cross-session CSRF", type: "OBJECT" },
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": aliceToken },
    });

    expect(response.status()).toBe(403);
    expect((await response.json()).error.code).toBe("CSRF_VALIDATION_FAILED");
  });

  test("an invalid image is rejected and a hostile filename is neutralized", async ({
    playwright,
  }) => {
    const context = await playwright.request.newContext({ baseURL: BASE_URL });
    await registerThroughApi(context, uniqueEmail("uploads"));
    const token = await csrfToken(context);

    const projectResponse = await context.post("/api/v1/projects", {
      data: { name: "Upload validation", type: "OBJECT" },
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": token },
    });
    expect(projectResponse.status()).toBe(201);
    const projectId = (await projectResponse.json()).id as string;

    const invalidResponse = await context.post(`/api/v1/projects/${projectId}/images`, {
      multipart: {
        file: {
          name: "payload.jpg",
          mimeType: "image/jpeg",
          buffer: Buffer.from("#!/bin/sh\necho not an image\n"),
        },
      },
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": token },
    });
    // The extension and declared type agree, so the content check must reject it.
    expect([400, 415]).toContain(invalidResponse.status());

    // A legitimate image with a path-traversal filename is stored under a
    // server-generated key; the response never exposes a storage path.
    const traversalResponse = await context.post(`/api/v1/projects/${projectId}/images`, {
      multipart: {
        file: {
          name: "../../escape.jpg",
          mimeType: "image/jpeg",
          buffer: readFileSync(OBJECT_IMAGE),
        },
      },
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": token },
    });
    expect(traversalResponse.status()).toBe(201);
    const body = await traversalResponse.json();
    expect(body.original_filename).toBe("escape.jpg");
    expect(body.storage_key).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("projects/");

    await context.delete(`/api/v1/projects/${projectId}`, {
      headers: { ...ORIGIN_HEADER, "X-CSRF-Token": token },
    });
  });

  test("the login surface rejects malformed credentials without leaking state", async ({
    playwright,
  }) => {
    const context = await playwright.request.newContext({ baseURL: BASE_URL });

    const response = await context.post("/api/v1/auth/login", {
      data: { email: "not-a-valid-email", password: "x" },
      headers: ORIGIN_HEADER,
    });

    expect(response.status()).toBe(422);
    expect((await response.json()).error.code).toBe("VALIDATION_ERROR");
  });
});
