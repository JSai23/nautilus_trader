# Specialization: Python Development

> This layers on top of the **worker** base primitive. These are concrete principles for writing Python — not aspirations, but decisions you make repeatedly during implementation.

---

## Writing Code

### Readability
- Code reads top-down. Module-level constants and types at the top, public functions next, private helpers below. Classes follow the same: public methods first, private after.
- Name things for what they represent. `connection_pool` not `cp`. `retry_count` not `n`. No single-letter variables outside comprehensions and trivial lambdas.
- If a function needs a comment explaining what it does, rename it or restructure it. Comments explain *why*, not *what*.
- One concept per function. If you're writing "and" in a function name, split it.

### Types as Design
- **Use type hints everywhere.** All function signatures, class attributes, and return types. No `Any` unless you're wrapping truly untyped external data.
- **`dataclass` or `NamedTuple` for data, not dicts.** `{"user_id": 1, "name": "x"}` becomes `@dataclass class User`. Dicts are for genuinely dynamic keys.
- **Enums for fixed choices.** `class Status(Enum): ACTIVE = "active"` not magic strings scattered across the codebase.
- **`NewType` for domain concepts at boundaries.** `UserId = NewType("UserId", int)` prevents silently passing a quantity where a user_id was expected.
- **Pydantic models at system boundaries** (API input/output, config parsing, external data). Dataclasses for internal data structures.
- **`Protocol` over ABC when you just need structural typing.** Don't force inheritance for "has a `.process()` method."

### Error Handling
- **Specific exceptions over generic ones.** `raise ValueError("user_id must be positive")` not `raise Exception("bad input")`.
- **Custom exception classes when callers need to catch specific cases.** Inherit from a module-level base: `class MyServiceError(Exception)` then `class NotFoundError(MyServiceError)`.
- **Never bare `except:` or `except Exception:` that silently swallows.** Catch what you can handle, let everything else propagate.
- **No exceptions for control flow.** Don't use try/except where an if-check is clearer. `if key in dict` not `try: dict[key] except KeyError`.
- **Context in error messages.** `f"User {user_id} not found in {table}"` not `"not found"`.

### Zero Bloat
- **No dead code.** No commented-out blocks. No `# TODO: remove this`. If it's not used, delete it.
- **No premature `__all__`.** Export what's needed. Use `_private` prefix convention for module internals.
- **Dependencies earn their place.** Before adding a package: can you write this in 20 lines? Is it maintained? `requests` for one HTTP call when `urllib` works is bloat. `sqlalchemy` for database access is not.
- **One way to do things.** If the codebase uses `httpx`, don't introduce `requests`. If it uses `pathlib`, don't use `os.path`. Match what exists.

### No Over-Engineering
- **No abstraction for one use case.** Three similar blocks of code are fine. Extract when the pattern repeats a fourth time and you can name the abstraction clearly.
- **No premature base classes.** A class with one subclass is not an abstraction — it's indirection. Use a concrete class until you have two genuine variants.
- **No wrapper classes that just delegate.** If your `ServiceClient` just wraps `httpx.Client` and forwards every call, remove it.
- **No metaclasses, descriptors, or `__init_subclass__` unless the problem genuinely requires them.** 99% of the time a function or a simple class is enough.

---

## Writing Tests

### Behavior First
- Before writing a test, write the list of behaviors. "Given X, when Y, then Z." Tests implement these behaviors, not lines of code.
- **Happy paths and error paths both matter.** If the function can raise, test that it raises correctly — right exception type, right message, no silent failures.
- **Don't test the language.** Python's type system and standard library already work. Don't test that `list.append` appends.

### Test Design
- **`pytest` over `unittest`.** Plain functions, plain asserts, fixtures for setup. No class-based test inheritance hierarchies.
- **Avoid mocking.** Use real implementations wherever possible. If you need a database, use an in-memory SQLite or temp file. If you need HTTP, use `httpx` mock transport or a local test server. Mock only at true system boundaries (external APIs you don't control).
- **Tests are deterministic.** No sleeps, no system clock, no race conditions. Inject time and randomness via parameters or fixtures.
- **Never pollute source code to make tests possible.** No `if TESTING:` branches. No public methods that exist only for tests. If you can't test it through the public API, the API is wrong — fix the API.
- **Unit tests live next to the code** in `test_*.py` files or a `tests/` subdirectory within the package.
- **Integration tests live in a top-level `tests/` directory.** These test that pieces compose correctly.
- **Test the unobvious.** Empty input, None where unexpected, max values, unicode, concurrent access, ordering assumptions. These are where bugs live.
- **If all tests pass, the software works.** If you can break the software without breaking a test, you're missing a test.
- **Use `conftest.py` for shared fixtures**, not base test classes. Fixtures compose; inheritance doesn't.

---

## Solving Problems

- **Find the root cause.** A workaround that fixes the symptom and hides the cause is worse than the bug. If a function raises unexpectedly, don't wrap it in try/except — find out why it raises.
- **Never write hacky code to fix code.** If the fix feels wrong, the diagnosis is probably wrong. Step back, re-read, add logging, reproduce in a test.
- **Reproduce first, fix second.** Write a failing test that demonstrates the bug before touching any implementation code. The test stays as a regression guard.
- **Problems cascade — fix the chain.** When you find a bug, use LSP/grep to trace callers and related functions. If the same wrong assumption exists elsewhere, fix all of them now.

---

## Cleaning Up

- **Linters are law.** `ruff` (or `flake8` + `isort` + `black` if that's the codebase convention). Fix every warning. Don't `# noqa` without a comment justifying why.
- **Formatter is not optional.** `black` or `ruff format`. One style, no exceptions.
- **Dead imports, dead variables, dead functions — remove immediately.** Don't leave them for "later."
- **Always try to simplify.** After implementing, re-read and ask: can this be shorter? Can two classes become one? Can a three-step process become two?
- **Small files with packages over large files.** When a file grows past ~300 lines, split by responsibility into a package with `__init__.py`. Don't let files become catch-alls.
- **Find and clean redundant types.** If two classes carry the same data with different names, unify them. Use `TypeAlias` when a complex type appears repeatedly.
- **Refactor when the code tells you to**, not on a schedule. Three functions with the same first four lines? Extract. A function over 40 lines? Split.
- **Cleanup is not a separate task.** Every implementation session leaves the code cleaner than it found it in the areas it touches.

---

## Living Docs

Living docs are **hindsight** — they describe what IS, not what was planned. Plans are foresight. After you implement something, document what actually exists.

- **After implementing, update or create living docs near what changed.** System-level docs go in `design-docs/`, package-level in `{package}/design-docs/`. Every new doc must be linked from `ARCHITECTURE.md` so the next session can find it.
- **Living docs describe structure, contracts, data models, and test strategy.** Not aspirational descriptions — the current reality of how the system works.
- **Staleness is a bug.** If the code changed and the doc didn't, fix the doc immediately. Don't defer.
- **Condense as understanding stabilizes.** Early docs are verbose with context. Once stable, tighten. Remove scaffolding prose. Expand when you discover non-obvious behavior.

### Python-Specific

- **Module-level docstrings** explain why the module exists and how it relates to the system. One paragraph.
- **Public functions and classes get docstrings.** One-line summary. Add `Args:` / `Returns:` / `Raises:` only when the type hints don't tell the full story. Don't restate what the signature already says.
- **No docstrings on private functions** unless the logic is genuinely surprising.
