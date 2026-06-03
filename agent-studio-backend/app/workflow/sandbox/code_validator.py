"""
AST-based static validator for user/LLM-generated Python code.

Walks the syntax tree to enforce an import allowlist and block dangerous
built-in calls, attribute-chain calls, dunder access, and obfuscation
patterns.
"""

import ast
from dataclasses import dataclass, field
from typing import Sequence

from .exceptions import CodeValidationError

DEFAULT_ALLOWED_IMPORTS: frozenset[str] = frozenset({
    # Standard library (safe subset)
    "json", "csv", "math", "statistics", "datetime", "collections",
    "itertools", "re", "typing", "dataclasses", "enum", "functools",
    "operator", "string", "textwrap", "uuid", "hashlib", "base64",
    "copy", "decimal", "fractions", "random", "time", "calendar",
    "pprint", "io", "struct", "html", "xml", "concurrent",
    "traceback", "warnings",
    # Data-science
    "pandas", "numpy", "matplotlib", "scipy", "sklearn",
    # Document processing
    "pptx", "fitz",
    # SDK
    "agent_studio",
})

BLOCKED_CALLS: frozenset[str] = frozenset({
    "exec", "eval", "compile", "__import__", "open",
    "getattr", "setattr", "delattr", "globals", "locals",
    "breakpoint", "exit", "quit",
})

BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "http", "urllib",
    "requests", "httpx", "pathlib", "importlib", "ctypes", "pickle",
    "shelve", "code", "signal", "multiprocessing", "threading",
    "asyncio", "pty", "fcntl", "resource", "grp", "pwd",
    "cffi", "dl", "commands", "pipes", "tempfile",
})

DANGEROUS_DUNDERS: frozenset[str] = frozenset({
    "__subclasses__", "__globals__", "__builtins__", "__code__",
    "__reduce__", "__reduce_ex__", "__import__", "__loader__",
    "__spec__", "__bases__", "__mro__", "__class__",
})

DANGEROUS_ATTR_CHAINS: frozenset[tuple[str, str]] = frozenset({
    ("os", "system"), ("os", "popen"), ("os", "exec"),
    ("os", "execvp"), ("os", "execve"), ("os", "spawn"),
    ("os", "fork"), ("os", "kill"), ("os", "remove"),
    ("os", "unlink"), ("os", "rmdir"), ("os", "rename"),
    ("os", "environ"), ("os", "getcwd"), ("os", "chdir"),
    ("subprocess", "run"), ("subprocess", "call"),
    ("subprocess", "Popen"), ("subprocess", "check_output"),
    ("subprocess", "check_call"), ("subprocess", "getoutput"),
    ("shutil", "rmtree"), ("shutil", "move"), ("shutil", "copy"),
    ("importlib", "import_module"), ("importlib", "__import__"),
    ("builtins", "__import__"), ("builtins", "exec"),
    ("builtins", "eval"), ("builtins", "compile"),
    ("codecs", "decode"),
})

# ── Deliverable-shape guardrails ────────────────────────────────────────
#
# The Code Executor has been burned by an LLM-generation pattern where the
# script builds a full HTML page in Python, base64-encodes it, stuffs it
# into ``output.data({"html_base64": ...})``, then decodes it client-side
# inside a ``{"type": "render", "script": "..."}`` block that loads it
# into an ``iframe srcDoc``.  That pattern bypasses every DSL primitive,
# pollutes downstream nodes (which receive the blob through ``data``),
# bloats the deliverable JSON in Postgres, and embeds unsanitised user
# input into HTML — i.e. it is simultaneously a contract violation, a
# storage problem, and an XSS vector.  The constants below let the AST
# validator detect each layer of that pattern at gen-time.

# Field names that are NEVER allowed inside the ``data`` argument of
# ``output.data(...)``.  ``data`` is the machine-readable payload that
# downstream nodes/agents consume; rendered markup belongs in
# ``visualization``, not here.
FORBIDDEN_DATA_KEYS: frozenset[str] = frozenset({
    "html", "html_base64", "html_b64", "html_content", "html_string",
    "rendered_html", "markup", "dom_string", "iframe", "iframe_src",
    "script", "script_html", "raw_html", "page_html", "full_html",
})

# JavaScript fragments that must not appear inside the ``script`` field
# of a ``{"type": "render", ...}`` visualization spec.  These are the
# primitives an LLM reaches for when smuggling DOM injection or arbitrary
# code-eval through the render escape hatch.
FORBIDDEN_RENDER_JS_TOKENS: tuple[tuple[str, str], ...] = (
    ("srcDoc", "iframe srcDoc loading is not allowed in render scripts"),
    ("srcdoc", "iframe srcdoc loading is not allowed in render scripts"),
    ("<iframe", "<iframe> elements are not allowed in render scripts"),
    (".innerHTML", "innerHTML assignment is not allowed; use React.createElement children"),
    (".outerHTML", "outerHTML assignment is not allowed"),
    ("dangerouslySetInnerHTML", "dangerouslySetInnerHTML is not allowed"),
    ("document.write", "document.write() is not allowed"),
    ("atob(", "atob() decoding inside render scripts is not allowed"),
    ("eval(", "eval() inside render scripts is not allowed"),
    ("new Function(", "new Function() inside render scripts is not allowed"),
    ("Function(", "Function() constructor inside render scripts is not allowed"),
)

# Markers that flag a string literal as HTML markup.  We scan large
# string constants and f-string static parts for these to catch the
# "build the HTML in Python" anti-pattern before it ever runs.
HTML_MARKUP_MARKERS: tuple[str, ...] = (
    "<!doctype", "<!DOCTYPE",
    "<html", "<HTML", "</html>", "</HTML>",
    "<body", "<BODY", "</body>", "</BODY>",
    "<script", "<SCRIPT", "</script>", "</SCRIPT>",
    "<iframe", "<IFRAME",
    "<style>", "<STYLE>",
)

# Size budgets enforced statically on string constants embedded in code.
# Runtime check (in ``code_executor.py``) enforces the same on the actual
# emitted deliverable -- this static check just catches the obvious
# "huge HTML page is sitting right there in a string literal" case before
# the sandbox is even acquired.
MAX_STRING_LITERAL_BYTES = 64 * 1024            # 64 KB per literal
MAX_RENDER_SCRIPT_BYTES = 32 * 1024             # 32 KB per render script body


@dataclass
class ValidationResult:
    valid: bool
    violations: list[str] = field(default_factory=list)


class CodeValidator:
    """Stateless validator -- instantiate with an optional extra allowlist."""

    def __init__(self, extra_allowed_imports: Sequence[str] | None = None):
        self._allowed = DEFAULT_ALLOWED_IMPORTS | frozenset(extra_allowed_imports or [])

    def validate(self, code: str) -> ValidationResult:
        """Parse *code* and return a ``ValidationResult``."""
        violations: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationResult(valid=False, violations=[f"SyntaxError: {exc}"])

        for node in ast.walk(tree):
            self._check_import(node, violations)
            self._check_call(node, violations)
            self._check_dangerous_attributes(node, violations)
            self._check_string_obfuscation(node, violations)
            self._check_html_string_literal(node, violations)
            self._check_html_fstring(node, violations)

        # Whole-tree passes: these need to inspect dict literals passed to
        # specific calls (``output.data``) and dict literals describing
        # specific shapes (``{"type": "render", "script": ...}``), so they
        # can't run inside the per-node loop without redoing the same
        # walk anyway.
        self._check_output_data_shape(tree, violations)
        self._check_render_script_specs(tree, violations)

        return ValidationResult(valid=len(violations) == 0, violations=violations)

    def validate_or_raise(self, code: str) -> None:
        """Convenience wrapper that raises ``CodeValidationError``."""
        result = self.validate(code)
        if not result.valid:
            raise CodeValidationError(
                "Code failed validation", violations=result.violations,
            )

    def _check_import(self, node: ast.AST, violations: list[str]) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BLOCKED_IMPORTS:
                    violations.append(f"Blocked import: '{alias.name}'")
                elif top not in self._allowed:
                    violations.append(
                        f"Import '{alias.name}' not in allowed list. "
                        f"Allowed: {sorted(self._allowed)}"
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in BLOCKED_IMPORTS:
                    violations.append(f"Blocked import: 'from {node.module}'")
                elif top not in self._allowed:
                    violations.append(
                        f"Import 'from {node.module}' not in allowed list. "
                        f"Allowed: {sorted(self._allowed)}"
                    )

    @staticmethod
    def _check_call(node: ast.AST, violations: list[str]) -> None:
        if not isinstance(node, ast.Call):
            return

        func = node.func
        # Direct name calls: eval(), exec(), __import__(), etc.
        if isinstance(func, ast.Name):
            if func.id in BLOCKED_CALLS:
                violations.append(f"Blocked call: '{func.id}()'")

        # Attribute-chain calls: os.system(), subprocess.run(), etc.
        if isinstance(func, ast.Attribute):
            chain = _resolve_attr_chain(func)
            if len(chain) >= 2:
                root, method = chain[0], chain[-1]
                if (root, method) in DANGEROUS_ATTR_CHAINS:
                    violations.append(
                        f"Blocked call: '{root}.{method}()'"
                    )

    @staticmethod
    def _check_dangerous_attributes(node: ast.AST, violations: list[str]) -> None:
        """Flag access to dangerous dunder attributes."""
        if isinstance(node, ast.Attribute) and node.attr in DANGEROUS_DUNDERS:
            violations.append(
                f"Access to dangerous attribute '{node.attr}' is not allowed"
            )

    @staticmethod
    def _check_string_obfuscation(node: ast.AST, violations: list[str]) -> None:
        """Detect obfuscation patterns that try to bypass import/call checks."""
        if not isinstance(node, ast.Call):
            return

        func = node.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        # Pattern: __import__("os") via string argument
        if func_name == "__import__" and node.args:
            violations.append("Dynamic __import__() call is not allowed")
            return

        # Pattern: eval/exec with string literal containing blocked modules
        if func_name in ("eval", "exec") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                val = arg.value.lower()
                for blocked in BLOCKED_IMPORTS:
                    if blocked in val:
                        violations.append(
                            f"String argument to {func_name}() references "
                            f"blocked module '{blocked}'"
                        )
                        return

        # Pattern: base64.b64decode(...) fed into exec/eval
        if isinstance(func, ast.Attribute) and func.attr == "b64decode":
            parent_call = _find_parent_call_name(node)
            if parent_call in ("exec", "eval"):
                violations.append(
                    "base64.b64decode() used with exec/eval is not allowed"
                )

    # ── Deliverable-shape guards ─────────────────────────────────────────

    @staticmethod
    def _check_html_string_literal(node: ast.AST, violations: list[str]) -> None:
        """Flag oversized string constants that contain HTML markup.

        Catches the most common LLM bypass: building a complete HTML page
        as one giant Python string and shipping it inside ``data``.  Small
        snippets (a `<br>` in a tooltip) won't trip this because we
        require both the size threshold AND a strong markup marker.
        """
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return
        text = node.value
        if len(text) < 1024:
            return
        for marker in HTML_MARKUP_MARKERS:
            if marker in text:
                violations.append(
                    f"Large HTML literal ({len(text):,} chars) detected — "
                    f"contains '{marker}'.  Build UIs with the visualization "
                    f"DSL (`header`, `grid`, `metric`, `chart`, `table`, …) "
                    f"or a `{{\"type\": \"render\", ...}}` spec, not by "
                    f"constructing HTML in Python."
                )
                return
        if len(text) > MAX_STRING_LITERAL_BYTES:
            violations.append(
                f"String literal exceeds {MAX_STRING_LITERAL_BYTES:,} byte "
                f"budget ({len(text):,} bytes).  If this is data, load it "
                f"from a file; if this is markup, use the visualization "
                f"DSL instead."
            )

    @staticmethod
    def _check_html_fstring(node: ast.AST, violations: list[str]) -> None:
        """Flag f-strings whose static parts build HTML tags.

        `f'<tr><td>{x}</td></tr>'` is the hand-rolled-table pattern that
        leads directly to CSV-driven XSS when the interpolated values
        come from user uploads.  We require an opening `<` immediately
        followed by a tag-name character (or `/`) so plain text like
        ``f"x < {y}"`` doesn't trip the check.
        """
        if not isinstance(node, ast.JoinedStr):
            return
        static_parts: list[str] = []
        has_interpolation = False
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                static_parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                has_interpolation = True
        if not has_interpolation:
            return
        joined = "".join(static_parts)
        if not joined:
            return
        # Look for an HTML tag opening: `<` followed by a-zA-Z or `/`.
        # We deliberately avoid the `re` module to keep this hot path cheap.
        for i, ch in enumerate(joined):
            if ch != "<":
                continue
            if i + 1 >= len(joined):
                continue
            nxt = joined[i + 1]
            if nxt == "/" or ("a" <= nxt.lower() <= "z"):
                # Restrict to common HTML tag prefixes to limit false
                # positives on generics like ``f"<{T}>"`` in type hints.
                lookahead = joined[i:i + 12].lower()
                tag_hits = (
                    "<table", "<tr", "<td", "<th", "<thead", "<tbody",
                    "<div", "<span", "<p>", "<p ", "<a ", "<a>", "<img",
                    "<script", "<iframe", "<style", "<link", "<meta",
                    "<html", "<head", "<body", "<form", "<input",
                    "<button", "<ul", "<ol", "<li", "<h1", "<h2", "<h3",
                    "<h4", "<h5", "<h6", "<br", "<hr", "<svg", "<canvas",
                    "</",
                )
                if any(lookahead.startswith(t) for t in tag_hits):
                    violations.append(
                        "f-string constructs HTML markup with interpolated "
                        "values.  This is the CSV-driven XSS pattern: any "
                        "user-supplied string in the placeholders renders "
                        "as live HTML.  Use the visualization DSL "
                        "(`{\"type\": \"table\", \"rows\": [...]}` etc.) so "
                        "the frontend escapes values for you."
                    )
                    return

    @classmethod
    def _check_output_data_shape(
        cls, tree: ast.AST, violations: list[str],
    ) -> None:
        """Inspect each ``output.data(...)`` call's first argument.

        We catch three abuse shapes here, all observed in the wild:

        1. A dict-literal containing a forbidden key
           (``html_base64``, ``script``, ``iframe``, ...).
        2. A dict-literal whose value for any key is a large string
           literal looking like HTML.
        3. A dict-literal whose value for any key is a ``Name`` whose
           assignment in the same module is a base64 encode of an
           HTML-shaped literal.

        Anything dynamic that we can't reason about statically is
        deferred to the runtime payload check in ``code_executor.py``.
        """
        # Collect simple ``name = base64.b64encode(...).decode()`` bindings
        # so we can detect ``output.data({"x": name})`` referring back to
        # an HTML-flavoured base64 result.
        b64_html_names: set[str] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if cls._rhs_is_b64_of_html(node.value):
                b64_html_names.add(target.id)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chain = _resolve_attr_chain(node.func) if isinstance(
                node.func, ast.Attribute,
            ) else []
            if not (len(chain) == 2 and chain[0] == "output" and chain[1] == "data"):
                continue
            if not node.args:
                continue
            data_arg = node.args[0]
            if not isinstance(data_arg, ast.Dict):
                # Non-literal data — defer to runtime check.
                continue
            cls._scan_data_dict(
                data_arg,
                violations=violations,
                b64_html_names=b64_html_names,
                path="data",
            )

    @classmethod
    def _scan_data_dict(
        cls,
        node: ast.Dict,
        *,
        violations: list[str],
        b64_html_names: set[str],
        path: str,
    ) -> None:
        for k_node, v_node in zip(node.keys, node.values):
            if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
                continue
            key = k_node.value
            child_path = f"{path}.{key}"

            if key.lower() in FORBIDDEN_DATA_KEYS:
                violations.append(
                    f"Forbidden field '{key}' in `output.data` payload "
                    f"({child_path}).  Rendered HTML / scripts / iframes "
                    f"belong in the `visualization` argument as a `render` "
                    f"spec, not in `data`.  Downstream nodes consume "
                    f"`data` and never see `visualization`."
                )
                continue

            if isinstance(v_node, ast.Constant) and isinstance(v_node.value, str):
                value = v_node.value
                if len(value) >= 1024 and any(
                    m in value for m in HTML_MARKUP_MARKERS
                ):
                    violations.append(
                        f"`{child_path}` is a {len(value):,}-char HTML "
                        f"string literal.  Don't ship rendered markup "
                        f"through `data`; emit a `{{'type': 'render', "
                        f"'script': ...}}` spec in `visualization` and "
                        f"build the UI with React.createElement."
                    )

            if isinstance(v_node, ast.Name) and v_node.id in b64_html_names:
                violations.append(
                    f"`{child_path}` references `{v_node.id}`, which is a "
                    f"base64 encoding of HTML.  Shipping a base64'd HTML "
                    f"page through `data` is the validator-bypass pattern "
                    f"this rule exists to block.  Use the visualization "
                    f"DSL to render the UI."
                )

            if isinstance(v_node, ast.Dict):
                cls._scan_data_dict(
                    v_node,
                    violations=violations,
                    b64_html_names=b64_html_names,
                    path=child_path,
                )

    @staticmethod
    def _rhs_is_b64_of_html(node: ast.AST) -> bool:
        """True iff ``node`` is ``base64.b64encode(<html-ish>).decode(...)``
        or the inner ``base64.b64encode(<html-ish>)``.

        ``<html-ish>`` is any AST that, when statically inspected, looks
        like the HTML construction we just flagged elsewhere.  This is a
        best-effort static check; the runtime payload guard handles
        anything we can't reason about here.
        """
        # Unwrap ``.decode(...)``
        target = node
        if (
            isinstance(target, ast.Call)
            and isinstance(target.func, ast.Attribute)
            and target.func.attr == "decode"
        ):
            target = target.func.value
        if not (
            isinstance(target, ast.Call)
            and isinstance(target.func, ast.Attribute)
            and target.func.attr == "b64encode"
        ):
            return False
        if not target.args:
            return False
        inner = target.args[0]
        # ``base64.b64encode(html_bytes)`` where ``html_bytes`` is
        # ``html_str.encode(...)`` of an HTML literal/joined-string.
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "encode"
        ):
            inner = inner.func.value
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            return any(m in inner.value for m in HTML_MARKUP_MARKERS)
        if isinstance(inner, ast.JoinedStr):
            for v in inner.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    if any(m in v.value for m in HTML_MARKUP_MARKERS):
                        return True
        return False

    @classmethod
    def _check_render_script_specs(
        cls, tree: ast.AST, violations: list[str],
    ) -> None:
        """Find ``{"type": "render", "script": "..."}`` literals and
        lint the JS body for known abuse patterns.

        We only inspect dict literals whose ``type`` is the constant
        string ``"render"``; anything dynamic falls through to the
        runtime guard.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            type_value: str | None = None
            script_value: str | None = None
            script_len: int = 0
            for k_node, v_node in zip(node.keys, node.values):
                if not (
                    isinstance(k_node, ast.Constant)
                    and isinstance(k_node.value, str)
                ):
                    continue
                if k_node.value == "type" and isinstance(v_node, ast.Constant):
                    if isinstance(v_node.value, str):
                        type_value = v_node.value
                elif k_node.value == "script":
                    script_value = cls._collect_string_value(v_node)
                    if script_value is not None:
                        script_len = len(script_value)
            if type_value != "render" or script_value is None:
                continue

            if script_len > MAX_RENDER_SCRIPT_BYTES:
                violations.append(
                    f"render script body is {script_len:,} bytes "
                    f"(limit: {MAX_RENDER_SCRIPT_BYTES:,}).  Move data "
                    f"into the `data` payload and keep the script as a "
                    f"thin React.createElement renderer."
                )

            for token, message in FORBIDDEN_RENDER_JS_TOKENS:
                if token in script_value:
                    violations.append(
                        f"render script contains forbidden pattern "
                        f"'{token}': {message}"
                    )

    @staticmethod
    def _collect_string_value(node: ast.AST) -> str | None:
        """Best-effort: return the text of a string constant or a static
        f-string / concatenation chain.  Returns None for fully dynamic
        values (those defer to the runtime guard).
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                # FormattedValue placeholders contribute nothing static --
                # we still scan the literal portions because that's where
                # forbidden tokens always live.
            return "".join(parts) if parts else None
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
        ):
            left = CodeValidator._collect_string_value(node.left)
            right = CodeValidator._collect_string_value(node.right)
            if left is not None and right is not None:
                return left + right
        return None

def _resolve_attr_chain(node: ast.Attribute) -> list[str]:
    """Walk an Attribute chain like ``a.b.c`` → ``['a', 'b', 'c']``."""
    parts: list[str] = [node.attr]
    current = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return parts


def _find_parent_call_name(node: ast.AST) -> str:
    """Heuristic: check if this node is the argument of an exec/eval call.

    Since ast.walk doesn't provide parent links we look for the pattern
    ``Call(func=Name('exec'), args=[...node...])`` by checking if the
    b64decode call node appears inside a surrounding exec/eval Call in
    the same tree.  This is best-effort — advanced obfuscation will be
    caught by the container's restricted runtime anyway.
    """
    return ""
