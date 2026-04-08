## Writing Gleam Code

- Never assume Gleam stdlib functions exist — Gleam is underrepresented in training data. Research at hexdocs.pm when even slightly unsure.
- Use `gleam check` constantly — it's extremely fast.
- Spawn subagents for research to keep the main context clean.

---

## Code Style Rules

### Never silently discard errors

- `Error(_) ->` is banned, especially if the error type is `Nil`. Always bind and/or log with `string.inspect`. You can also use `Error(Nil) ->` for Nil error values.
- Same for `fn(_err)` and `result.map_error(fn(_) { ... })` — always include the original error.

### No nested case pyramids

2+ levels of nested `case` where every error branch returns the same fallback → refactor to `result.try`/`result.map`/`use` chains or extract a helper.

### Always use `use` for result.try/result.map — never write `Error(e) -> Error(e)`

```gleam
// BAD
case first_op() {
  Ok(v) -> second_op(v)
  Error(e) -> Error(e)
}

// GOOD — result.try when body returns Result
use v <- result.try(first_op())
second_op(v)

// GOOD — result.map when body returns a plain value
use #(p, expr) <- result.map(parse_expression(parser))
transform(expr)
```

When the Ok value is `Nil`, bind `Nil` explicitly — never `use _ <-`.

### Always use `use` for callback-last functions

```gleam
// BAD
math_unary(args, state, fn(x) { Finite(float.absolute_value(x)) })

// GOOD
use x <- math_unary(args, state)
Finite(float.absolute_value(x))
```

But pass functions directly when they already match: `conditional_jump(state, target, value.is_truthy)`

### Don't use map/map_error for side effects

Use explicit `case` when a branch has side effects (logging, IO). `let _ = result.map(...)` is a code smell.

### Result vs Option

- `Option` — a value that may not be present (empty slot, nothing here)
- `Result` — an operation that can fail
- In our code, prefer `Option` over `Result(a, Nil)` for simple lookups so the compiler catches API changes.

### Prefer combinators over verbose case

- `option.unwrap(x, default)` instead of `case x { Some(v) -> v; None -> default }`
- `option.map(x, f) |> option.unwrap(default)` instead of `case x { Some(v) -> f(v); None -> default }`
- `option.flatten` instead of `case x { Some(inner) -> inner; None -> None }`
- `dict.get(m, k) |> result.map(f) |> result.unwrap(default)` instead of case+transform+fallback
- Record constructors are functions: `list.map(items, Wrapper)` not `list.map(items, fn(x) { Wrapper(x) })`

---

## Gleam Reminders

Things LLMs commonly get wrong:

- No `if` — use `case` for all conditionals
- Guards can't contain function calls — bind the result first, then guard on it
- Only one `_` per function capture expression
- Label shorthand: `User(name:, age:)` when variable names match labels
- `bool.guard` is for existing booleans — don't convert values to bool just to use it
- `<>` pattern matches string prefixes: `"subscribe:" <> channel_name`
- `bool.lazy_guard` when the return value is expensive (function calls, IO)

---
