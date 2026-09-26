import process from "node:process";

async function readRequest() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function call(base, path, body = undefined) {
  const response = await fetch(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let parsed;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { response_type: "non_json" };
  }
  if (!response.ok) {
    throw new Error(`agentmemory_http_${response.status}`);
  }
  return parsed;
}

async function main() {
  const request = await readRequest();
  const base = request.connection?.agentmemory_url;
  if (typeof base !== "string" || !/^http:\/\/(127\.0\.0\.1|\[::1\]):[0-9]+$/.test(base)) {
    throw new Error("invalid_connection");
  }
  const operation = request.operation;
  const payload = request.payload ?? {};
  if (operation === "version") {
    const result = await call(base, "/agentmemory/health");
    return { status: "available", version: result?.version, engine_version: "0.11.2" };
  }
  if (operation === "health") {
    const result = await call(base, "/agentmemory/health");
    return { status: result?.status ?? "unknown", result };
  }
  if (operation === "save") {
    const result = await call(base, "/agentmemory/remember", payload);
    return { status: "saved", result };
  }
  if (operation === "search") {
    const result = await call(base, "/agentmemory/search", payload);
    return { status: "queried", result };
  }
  if (operation === "context") {
    const result = await call(base, "/agentmemory/context", payload);
    return { status: "assembled", result };
  }
  throw new Error("unsupported_operation");
}

try {
  const result = await main();
  process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) {
  process.stdout.write(
    `${JSON.stringify({ status: "error", code: error?.message ?? "worker_error" })}\n`,
  );
  process.exitCode = 2;
}
