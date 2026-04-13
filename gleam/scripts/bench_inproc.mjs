#!/usr/bin/env node
import { readFileSync } from 'node:fs'
import { performance } from 'node:perf_hooks'
import { quality_from_json_with_mode_preset, form_from_json_with_mode_preset } from '../build/dev/javascript/team2form_gleam/team2form_gleam.mjs'
import { None, Some } from '../build/dev/javascript/gleam_stdlib/gleam/option.mjs'
import { Ok } from '../build/dev/javascript/team2form_gleam/gleam.mjs'
import {
  Mode$Compat,
  Mode$Paper,
  WeightPreset$LiveCompat,
  WeightPreset$DocsRecommended,
  WeightPreset$PaperBalanced,
} from '../build/dev/javascript/team2form_gleam/team2form_gleam/modes.mjs'

function usage() {
  process.stderr.write(
    'Usage: bench_inproc.mjs <quality|form> <payload.json> <iterations> [mode] [preset|none]\n',
  )
  process.exit(2)
}

const [command, payloadPath, iterationsRaw, modeRaw, presetRaw] = process.argv.slice(2)
if (!command || !payloadPath || !iterationsRaw) {
  usage()
}

const iterations = Number.parseInt(iterationsRaw, 10)
if (!Number.isFinite(iterations) || iterations <= 0) {
  process.stderr.write('iterations must be a positive integer\n')
  process.exit(2)
}

const modeName = modeRaw ?? 'compat'
const mode =
  modeName === 'compat'
    ? Mode$Compat()
    : modeName === 'paper'
      ? Mode$Paper()
      : (() => {
          process.stderr.write(`invalid mode: ${modeName}\n`)
          process.exit(2)
        })()
const presetValue =
  !presetRaw || presetRaw === 'none'
    ? new None()
    : presetRaw === 'live_compat'
      ? new Some(WeightPreset$LiveCompat())
      : presetRaw === 'docs_recommended'
        ? new Some(WeightPreset$DocsRecommended())
        : presetRaw === 'paper_balanced'
          ? new Some(WeightPreset$PaperBalanced())
          : (() => {
              process.stderr.write(`invalid preset: ${presetRaw}\n`)
              process.exit(2)
            })()
const none = new None()
const payload = readFileSync(payloadPath, 'utf8')

function runOne() {
  if (command === 'quality') {
    return quality_from_json_with_mode_preset(payload, mode, presetValue, false)
  }
  if (command === 'form') {
    return form_from_json_with_mode_preset(payload, mode, presetValue, false, none)
  }
  usage()
}

for (let i = 0; i < 5; i += 1) {
  const warmupResult = runOne()
  if (!(warmupResult instanceof Ok)) {
    process.stderr.write(`warmup failed: ${warmupResult[0]}\n`)
    process.exit(1)
  }
}

const start = performance.now()
for (let i = 0; i < iterations; i += 1) {
  const result = runOne()
  if (!(result instanceof Ok)) {
    process.stderr.write(`run failed: ${result[0]}\n`)
    process.exit(1)
  }
}
const elapsed = performance.now() - start
const perCallMs = elapsed / iterations

process.stdout.write(
  JSON.stringify({
    command,
    iterations,
    total_ms: elapsed,
    per_call_ms: perCallMs,
  }),
)
process.stdout.write('\n')
