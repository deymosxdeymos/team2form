#!/usr/bin/env node
import { createServer } from "node:http"
import { help_info, quality_from_json_with_mode_preset, form_from_json_with_mode_preset } from "../build/dev/javascript/team2form_gleam/team2form_gleam.mjs"
import { mode_from_string, weight_preset_from_string } from "../build/dev/javascript/team2form_gleam/team2form_gleam/modes.mjs"
import { None, Some } from "../build/dev/javascript/gleam_stdlib/gleam/option.mjs"
import { Ok } from "../build/dev/javascript/team2form_gleam/gleam.mjs"

const DEFAULT_MAX_CANDIDATE_TEAMS = 10000
const MAX_BODY_BYTES = 10 * 1024 * 1024
const REQUEST_URL_BASE = "http://localhost"

function env(name, fallback) {
  const value = process.env[name]
  return value === undefined || value === "" ? fallback : value
}

function unwrapStartupResult(label, result) {
  if (result instanceof Ok) return result[0]

  throw new Error(`${label}: ${result[0]}`)
}

function parseBool(name, fallback) {
  const raw = env(name, fallback ? "true" : "false").toLowerCase()
  if (raw === "true" || raw === "1" || raw === "yes") return true
  if (raw === "false" || raw === "0" || raw === "no") return false

  throw new Error(`${name} must be true or false`)
}

function parsePort() {
  const raw = env("TEAM2FORM_PORT", "8000")
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535 || String(parsed) !== raw) {
    throw new Error("TEAM2FORM_PORT must be an integer from 1 to 65535")
  }
  return parsed
}

function parseMaxCandidateTeams() {
  const raw = env("TEAM2FORM_MAX_CANDIDATE_TEAMS", String(DEFAULT_MAX_CANDIDATE_TEAMS))
  if (raw.toLowerCase() === "none") return new None()

  const parsed = Number.parseInt(raw, 10)
  if (!Number.isInteger(parsed) || parsed < 1 || String(parsed) !== raw) {
    throw new Error("TEAM2FORM_MAX_CANDIDATE_TEAMS must be a positive integer or none")
  }

  return new Some(parsed)
}

function parsePreset() {
  const raw = env("TEAM2FORM_PRESET", "")
  if (raw === "") return new None()

  const preset = unwrapStartupResult("TEAM2FORM_PRESET", weight_preset_from_string(raw))
  return new Some(preset)
}

const host = env("TEAM2FORM_HOST", "127.0.0.1")
const port = parsePort()
const mode = unwrapStartupResult("TEAM2FORM_MODE", mode_from_string(env("TEAM2FORM_MODE", "compat")))
const preset = parsePreset()
const normalizeWeights = parseBool("TEAM2FORM_NORMALIZE_WEIGHTS", false)
const maxCandidateTeams = parseMaxCandidateTeams()

function sendJson(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" })
  res.end(body)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let received = 0
    let tooLarge = false
    req.on("data", chunk => {
      if (tooLarge) return

      received += chunk.length
      if (received > MAX_BODY_BYTES) {
        tooLarge = true
        reject(Object.assign(new Error("Request body too large"), { statusCode: 413 }))
        return
      }
      chunks.push(chunk)
    })
    req.on("end", () => {
      if (!tooLarge) resolve(Buffer.concat(chunks).toString("utf8"))
    })
    req.on("error", reject)
  })
}

function handleResult(res, result) {
  if (result instanceof Ok) {
    sendJson(res, 200, result[0])
    return
  }

  const error = result[0]
  sendJson(res, 400, JSON.stringify({ detail: error }))
}

async function readJsonBody(req) {
  const body = await readBody(req)
  try {
    JSON.parse(body)
  } catch (error) {
    throw Object.assign(new Error(`Malformed JSON: ${error.message}`), { statusCode: 400 })
  }
  return body
}

const server = createServer(async (req, res) => {
  const method = req.method ?? "GET"
  const url = new URL(req.url ?? "/", REQUEST_URL_BASE).pathname

  try {
    if (method === "GET" && url === "/v1/help") {
      sendJson(res, 200, help_info())
      return
    }

    if (method === "POST" && url === "/v1/teamQuality") {
      const body = await readJsonBody(req)
      const result = quality_from_json_with_mode_preset(body, mode, preset, normalizeWeights)
      handleResult(res, result)
      return
    }

    if (method === "POST" && url === "/v1/teamFormation") {
      const body = await readJsonBody(req)
      const result = form_from_json_with_mode_preset(body, mode, preset, normalizeWeights, maxCandidateTeams)
      handleResult(res, result)
      return
    }

    sendJson(res, 404, JSON.stringify({ detail: "Not found" }))
  } catch (error) {
    const status = error.statusCode === 413 ? 413 : 400
    sendJson(res, status, JSON.stringify({ detail: error.message }))
  }
})

server.listen(port, host, () => {
  process.stdout.write(`team2form_gleam API listening at http://${host}:${port}\n`)
})
