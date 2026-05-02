#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process"
import { readFile } from "node:fs/promises"
import { createServer } from "node:net"
import { setTimeout as delay } from "node:timers/promises"

const ROOT = new URL("../", import.meta.url)
const SERVER = new URL("../gleam/scripts/server.mjs", import.meta.url)

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function assertClose(left, right, tolerance = 1e-9) {
  assert(Math.abs(left - right) <= tolerance, `Expected ${left} ~= ${right}`)
}

async function freePort() {
  const server = createServer()
  await new Promise((resolve, reject) => {
    server.once("error", reject)
    server.listen(0, "127.0.0.1", resolve)
  })
  const address = server.address()
  await new Promise(resolve => server.close(resolve))
  return address.port
}

async function requestJson(method, url, payload) {
  const response = await fetch(url, {
    method,
    headers: { "content-type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  return [response.status, await response.json()]
}

async function requestBytes(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { "content-type": "application/json" },
    body,
  })
  return [response.status, await response.json()]
}

async function waitUntilReady(baseUrl, process) {
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    assert(process.exitCode === null, "Node server exited before becoming ready")
    try {
      const [status] = await requestJson("GET", `${baseUrl}/v1/help`)
      if (status === 200) return
    } catch (_error) {
      await delay(100)
    }
  }
  throw new Error("Node server did not become ready")
}

async function assertQuality(baseUrl) {
  const payload = JSON.parse(
    await readFile(new URL("../examples/team-quality.json", import.meta.url), "utf8"),
  )
  const [status, body] = await requestJson("POST", `${baseUrl}/v1/teamQuality`, payload)
  assert(status === 200, `Expected quality status 200, got ${status}`)
  assertClose(body.quality, 0.6725)
  assertClose(body.skillScore, 1)
  assertClose(body.personalityScore, 0.075)
  assertClose(body.taskPreferenceScore, 1)
  assertClose(body.socialScore, 0.75)
  assert(JSON.stringify(body.assignments) === JSON.stringify({ b: ["s2"], a: ["s1"] }), "Unexpected quality assignments")
}

async function assertFormation(baseUrl) {
  const payload = JSON.parse(
    await readFile(new URL("../examples/team-formation.json", import.meta.url), "utf8"),
  )
  const [status, body] = await requestJson("POST", `${baseUrl}/v1/teamFormation`, payload)
  assert(status === 200, `Expected formation status 200, got ${status}`)
  assert(body.teams.length === 2, "Expected two formed teams")
  assert(body.teams[0].taskId === "t1", "Expected first task t1")
  assert(body.teams[1].taskId === "t2", "Expected second task t2")
  assertClose(body.teams[0].quality, 0.7224999999999999)
  assertClose(body.teams[1].quality, 0.7224999999999999)
}

async function assertInsufficientHeadcount(baseUrl) {
  const payload = {
    people: [
      { id: "p0", personality: { ei: 0, sn: 0, tf: 0, pj: 0 }, skills: [{ id: "s1", level: 1 }], preferences: [] },
      { id: "p1", personality: { ei: 0, sn: 0, tf: 0, pj: 0 }, skills: [{ id: "s1", level: 1 }], preferences: [] },
    ],
    tasks: [
      { id: "t0", teamSize: 3, skills: [{ id: "s1", level: 1, importance: 1 }], preferences: [] },
    ],
    alpha: 0.3,
    beta: 0.3,
    gamma: 0.2,
    delta: 0.2,
    initRandom: false,
  }
  const [status, body] = await requestJson("POST", `${baseUrl}/v1/teamFormation`, payload)
  assert(status === 400, `Expected insufficient headcount status 400, got ${status}`)
  assert(body.detail.includes("insufficient headcount"), "Expected insufficient headcount detail")
}

async function assertOversizedBody(baseUrl) {
  const body = `{"x":"${"a".repeat(10 * 1024 * 1024)}"}`
  const [status, response] = await requestBytes("POST", `${baseUrl}/v1/teamQuality`, body)
  assert(status === 413, `Expected oversized body status 413, got ${status}`)
  assert(response.detail === "Request body too large", "Expected oversized body detail")
}

function assertInvalidPortRejected() {
  const process = spawnSync("node", [SERVER.pathname], {
    cwd: ROOT.pathname,
    env: { ...processEnv(), TEAM2FORM_PORT: "8000abc" },
    encoding: "utf8",
  })
  assert(process.status !== 0, "Expected invalid port startup to fail")
  assert(
    process.stderr.includes("TEAM2FORM_PORT must be an integer from 1 to 65535"),
    "Expected invalid port error",
  )
}

function processEnv() {
  return globalThis.process.env
}

async function main() {
  assertInvalidPortRejected()

  const port = await freePort()
  const baseUrl = `http://127.0.0.1:${port}`
  const process = spawn("node", [SERVER.pathname], {
    cwd: ROOT.pathname,
    env: {
      ...processEnv(),
      TEAM2FORM_HOST: "127.0.0.1",
      TEAM2FORM_PORT: String(port),
      TEAM2FORM_MODE: "compat",
      TEAM2FORM_PRESET: "live_compat",
    },
    stdio: ["ignore", "pipe", "pipe"],
  })

  try {
    await waitUntilReady(baseUrl, process)
    const [status, help] = await requestJson("GET", `${baseUrl}/v1/help`)
    assert(status === 200, `Expected help status 200, got ${status}`)
    assert(JSON.stringify(help) === JSON.stringify({ name: "Edu2com", version: "0.1.0" }), "Unexpected help response")
    await assertQuality(baseUrl)
    await assertFormation(baseUrl)
    await assertInsufficientHeadcount(baseUrl)
    await assertOversizedBody(baseUrl)
  } finally {
    process.kill("SIGTERM")
  }

  console.log("Gleam HTTP smoke checks passed")
}

main().catch(error => {
  console.error(error)
  globalThis.process.exit(1)
})
