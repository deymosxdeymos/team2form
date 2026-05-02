#!/usr/bin/env node
import { readFileSync } from "node:fs"
import { quality_from_json, form_from_json } from "../build/dev/javascript/team2form_gleam/team2form_gleam.mjs"
import { None, Some } from "../build/dev/javascript/gleam_stdlib/gleam/option.mjs"
import { Ok } from "../build/dev/javascript/team2form_gleam/gleam.mjs"

function parseArgs(argv) {
  const out = {
    mode: "compat",
    preset: null,
    normalizeWeights: false,
    maxCandidateTeams: null,
    input: null,
  }

  const args = [...argv]
  while (args.length > 0) {
    const arg = args.shift()
    if (!arg) continue

    if (arg === "--mode") {
      out.mode = args.shift() ?? out.mode
      continue
    }
    if (arg === "--preset") {
      out.preset = args.shift() ?? null
      continue
    }
    if (arg === "--normalize-weights") {
      out.normalizeWeights = true
      continue
    }
    if (arg === "--max-candidate-teams") {
      const raw = args.shift()
      if (!raw) throw new Error("Missing value for --max-candidate-teams")
      const parsed = Number.parseInt(raw, 10)
      if (!Number.isFinite(parsed)) throw new Error("Invalid --max-candidate-teams")
      out.maxCandidateTeams = parsed
      continue
    }

    if (arg.startsWith("--")) {
      throw new Error(`Unknown flag: ${arg}`)
    }

    if (!out.input) {
      out.input = arg
      continue
    }

    throw new Error(`Unexpected argument: ${arg}`)
  }

  if (!out.input) throw new Error("Missing input path")
  return out
}

function maybe(value) {
  return value === null || value === undefined ? new None() : new Some(value)
}

function printResult(result) {
  if (result instanceof Ok) {
    const json = result[0]
    try {
      const parsed = JSON.parse(json)
      process.stdout.write(`${JSON.stringify(parsed, null, 2)}\n`)
    } catch (_error) {
      process.stdout.write(`${json}\n`)
    }
    return
  }

  const error = result[0]
  process.stderr.write(`team2form_gleam error: ${error}\n`)
  process.exit(1)
}

function main() {
  const [command, ...rest] = process.argv.slice(2)
  if (!command || (command !== "quality" && command !== "form")) {
    process.stderr.write("Usage: cli.mjs <quality|form> <input.json> [--mode compat|paper] [--preset live_compat|docs_recommended|paper_balanced] [--normalize-weights] [--max-candidate-teams N]\n")
    process.exit(1)
  }

  const parsed = parseArgs(rest)
  const inputJson = readFileSync(parsed.input, "utf8")

  const result =
    command === "quality"
      ? quality_from_json(inputJson, parsed.mode, maybe(parsed.preset), parsed.normalizeWeights)
      : form_from_json(
          inputJson,
          parsed.mode,
          maybe(parsed.preset),
          parsed.normalizeWeights,
          maybe(parsed.maxCandidateTeams),
        )

  printResult(result)
}

main()
