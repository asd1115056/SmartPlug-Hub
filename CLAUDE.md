# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python Style

- Follow **PEP 8**. Line length limit: **100 characters**.
- Use **type hints** on all function signatures (parameters and return types). Use `X | Y` union syntax (Python 3.10+), not `Optional[X]` or `Union[X, Y]`.
- Use **f-strings** for string formatting. Never `%` formatting or `.format()`.
- Use `dataclass` for data containers. Never plain dicts or tuples for structured data.
- Prefer `pathlib.Path` over `os.path`.
- Always use `async`/`await` for I/O — never blocking calls in async context.
- Imports: stdlib → third-party → local, each group separated by a blank line. No wildcard imports.

## Docstrings & Comments

- Module-level docstring: one-line summary of what the module does (not how).
- Class docstring: one line. Only add more if the class has non-obvious invariants.
- Method docstring: one line only if the name isn't self-explanatory. No param/return descriptions unless truly non-obvious.
- Inline comments: explain **why**, never what. Delete comments that restate the code.

## Naming

- `snake_case` for variables, functions, modules. `PascalCase` for classes. `UPPER_SNAKE_CASE` for module-level constants.
- Boolean variables and functions: prefix with `is_`, `has_`, or `can_`.
- Private methods/attributes: single leading underscore `_name`. Never double underscore.
- Abstract base classes: no `Abstract` prefix — name them by role (e.g. `DeviceBackend`, not `AbstractDeviceBackend`).

## Error Handling

- Catch the **narrowest** exception possible. Never bare `except:` or `except Exception` unless re-raising or logging at the top level.
- Custom exceptions inherit from a meaningful base (`Exception` or a domain base class), with a clear name ending in `Error`.
- Raise early; return results late. Validate inputs at function entry.

## JavaScript Style

- ES2020+ features are fine (`optional chaining`, `nullish coalescing`, `async/await`).
- `const` by default; `let` only when reassignment is needed. Never `var`.
- Arrow functions for callbacks and short expressions. Named `function` declarations for top-level functions.
- No semicolons. Single quotes for strings.
- DOM queries: cache results in `const` — never query the same element twice.
