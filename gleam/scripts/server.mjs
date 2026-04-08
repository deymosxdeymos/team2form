#!/usr/bin/env node
import { createServer } from "node:http"
import { help_info, quality_from_json, form_from_json } from "../build/dev/javascript/team2form_gleam/team2form_gleam.mjs"
import { None } from "../build/dev/javascript/gleam_stdlib/gleam/option.mjs"
import { Ok } from "../build/dev/javascript/team2form_gleam/gleam.mjs"

const host = "127.0.0.1"
const port = 8000

function sendJson(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" })
  res.end(body)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on("data", chunk => chunks.push(chunk))
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
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

const server = createServer(async (req, res) => {
  const method = req.method ?? "GET"
  const url = req.url ?? "/"

  if (method === "GET" && url === "/v1/help") {
    sendJson(res, 200, help_info())
    return
  }

  if (method === "POST" && url === "/v1/teamQuality") {
    const body = await readBody(req)
    const result = quality_from_json(body, "compat", new None(), false)
    handleResult(res, result)
    return
  }

  if (method === "POST" && url === "/v1/teamFormation") {
    const body = await readBody(req)
    const result = form_from_json(body, "compat", new None(), false, new None())
    handleResult(res, result)
    return
  }

  sendJson(res, 404, JSON.stringify({ detail: "Not found" }))
})

server.listen(port, host, () => {
  process.stdout.write(`team2form_gleam API listening at http://${host}:${port}\n`)
})
