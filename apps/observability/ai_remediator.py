import ast
import importlib.util
import inspect
import json
import logging
import os
import re
import traceback
from datetime import date, datetime
from typing import Any

import requests

from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLES_DIR = os.path.join(PROJECT_ROOT, "bundles")
AGENTS_MD_PATH = os.path.join(PROJECT_ROOT, "AGENTS.md")
CODE_SNIPPET_CHARS = 600


def _jsonable(value: Any) -> Any:
    """Convert DB/datetime values into JSON-serializable primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value

class LLMProviderGateway:
    """Model-Agnostic LLM Provider Gateway supporting Gemini, DeepSeek, OpenAI, Anthropic, and Ollama."""

    # Each provider reads its OWN key and has its OWN default model — picking
    # AI_REPAIR_PROVIDER=openai must never end up sending a leftover
    # GEMINI_API_KEY (or the Gemini default model name) to OpenAI's API.
    _PROVIDER_KEY_ENV = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    _PROVIDER_DEFAULT_MODEL = {
        "gemini": "gemini-1.5-flash",
        "openai": "gpt-4o-mini",
        "deepseek": "deepseek-chat",
        "anthropic": "claude-3-5-sonnet-20241022",
        "ollama": "qwen2.5-coder:7b",
    }

    def __init__(self):
        self.provider = os.getenv("AI_REPAIR_PROVIDER", "gemini").lower()
        provider_key_env = self._PROVIDER_KEY_ENV.get(self.provider)
        self.api_key = os.getenv("AI_REPAIR_API_KEY") or (
            os.getenv(provider_key_env, "") if provider_key_env else ""
        )
        self.model = os.getenv("AI_REPAIR_MODEL") or self._PROVIDER_DEFAULT_MODEL.get(
            self.provider, "gemini-1.5-flash"
        )
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def query_provider(self, prompt: str) -> str:
        """Routes prompt to configured LLM provider and returns raw generated text."""
        logger.info(f"Querying Model-Agnostic LLM Provider: '{self.provider}' (model: '{self.model}')")

        if self.provider == "gemini":
            return self._call_gemini(prompt)
        elif self.provider in ["openai", "deepseek"]:
            return self._call_openai_compatible(prompt)
        elif self.provider == "anthropic":
            return self._call_anthropic(prompt)
        elif self.provider == "ollama":
            return self._call_ollama(prompt)
        else:
            logger.warning(f"Unknown provider '{self.provider}', falling back to Gemini.")
            return self._call_gemini(prompt)

    def _call_gemini(self, prompt: str) -> str:
        """Queries Google Gemini REST API."""
        if not self.api_key:
            logger.warning("No API key configured for Gemini in .env (set AI_REPAIR_API_KEY or GEMINI_API_KEY).")
            return ""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=45)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                logger.error(f"Gemini API Error (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Failed to query Gemini API: {e}")
        return ""

    def _call_openai_compatible(self, prompt: str) -> str:
        """Queries OpenAI or DeepSeek OpenAI-compatible REST API."""
        if not self.api_key:
            logger.warning(f"No API key configured for {self.provider} in .env.")
            return ""
        base_url = "https://api.deepseek.com/v1" if self.provider == "deepseek" else "https://api.openai.com/v1"
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=45)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
            else:
                logger.error(f"{self.provider} API Error (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Failed to query {self.provider} API: {e}")
        return ""

    def _call_anthropic(self, prompt: str) -> str:
        """Queries Anthropic Claude REST API."""
        if not self.api_key:
            logger.warning("No API key configured for Anthropic in .env.")
            return ""
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}]
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=45)
            if res.status_code == 200:
                return res.json()["content"][0]["text"]
            else:
                logger.error(f"Anthropic API Error (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Failed to query Anthropic API: {e}")
        return ""

    def _call_ollama(self, prompt: str) -> str:
        """Queries local Ollama instance (100% free local execution on Apple Silicon Mac)."""
        url = f"{self.ollama_host}/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                return res.json().get("response", "")
            else:
                logger.error(f"Ollama API Error (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Failed to query local Ollama instance at {self.ollama_host}: {e}")
        return ""


class AIRemediatorEngine:
    """Generates diagnostic prompts and performs automated AST validation and code repairs."""

    def __init__(self):
        self.gateway = LLMProviderGateway()

    def load_product_context(self) -> str:
        """Loads master product context from AGENTS.md."""
        if os.path.exists(AGENTS_MD_PATH):
            with open(AGENTS_MD_PATH, encoding="utf-8") as f:
                return f.read()
        return "Product Context: DataHarbor open-core data platform."

    def validate_python_ast(self, python_code: str) -> tuple[bool, str]:
        """Validates generated Python code using standard library AST parser."""
        try:
            ast.parse(python_code)
            return True, "AST Validation PASSED (Zero Syntax Errors)"
        except SyntaxError as se:
            return False, f"AST SyntaxError: line {se.lineno}, col {se.offset}: {se.msg}"

    def extract_code_block(self, response_text: str) -> str:
        """Extracts raw python code from markdown triple backtick fences."""
        if "```python" in response_text:
            return response_text.split("```python")[1].split("```")[0].strip()
        elif "```" in response_text:
            return response_text.split("```")[1].split("```")[0].strip()
        return response_text.strip()

    _FILE_BLOCK_RE = re.compile(
        r"###\s*FILE:\s*(?P<path>\S+)\s*\n```(?:python)?\n(?P<code>.*?)```",
        re.DOTALL,
    )

    def extract_file_patches(self, response_text: str) -> dict[str, str]:
        """Parse one or more ``### FILE: <path>`` + code-fence blocks into {path: code}.

        Falls back to a single legacy code block (no FILE marker) under the sentinel
        key ``""`` when the model ignored the multi-file format — the caller maps
        that to the bundle's scraper.py, keeping single-file patches working.
        """
        matches = list(self._FILE_BLOCK_RE.finditer(response_text))
        if matches:
            return {m.group("path").strip(): m.group("code").strip() for m in matches}
        code = self.extract_code_block(response_text)
        return {"": code} if code else {}

    def _declared_extractor_ids(self, bundle_name: str) -> list[str]:
        """Extractor ids from this bundle's manifest.json requirements.extractors."""
        manifest_path = os.path.join(BUNDLES_DIR, bundle_name, "manifest.json")
        if not os.path.isfile(manifest_path):
            return []
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            from apps.extractor.requirements import parse_extractor_requirements

            raw = (manifest.get("requirements") or {}).get("extractors")
            reqs = parse_extractor_requirements(raw)
            return [r["name"] for r in reqs if r.get("name")]
        except Exception as e:
            logger.warning(f"Could not read declared extractors for '{bundle_name}': {e}")
            return []

    def _candidate_patch_files(self, bundle_name: str) -> dict[str, str]:
        """{relative_path: absolute_path} for scraper.py + every declared extractor's
        extractor.py — the full set of files --auto-fix is allowed to touch.

        Selector drift is usually in the *extractor* (parse-only HTML plugin), not the
        bundle's fetch/orchestration scraper.py — see AGENTS.md architecture. Patching
        scraper.py alone cannot fix that failure mode.
        """
        from apps.extractor.paths import EXTRACTORS_DIR

        candidates = {f"bundles/{bundle_name}/scraper.py": os.path.join(BUNDLES_DIR, bundle_name, "scraper.py")}
        for extractor_id in self._declared_extractor_ids(bundle_name):
            ext_path = os.path.join(EXTRACTORS_DIR, extractor_id, "extractor.py")
            if os.path.isfile(ext_path):
                candidates[f"extractors/{extractor_id}/extractor.py"] = ext_path
        return candidates

    def diagnose_bundle_failure(self, bundle_name: str) -> dict[str, Any]:
        """Collects failure logs and builds an AI remediation prompt covering
        scraper.py AND every extractor.py the bundle declares."""
        scraper_path = os.path.join(BUNDLES_DIR, bundle_name, "scraper.py")
        candidate_files = self._candidate_patch_files(bundle_name)

        sources = []
        for relpath, abspath in candidate_files.items():
            content = ""
            if os.path.exists(abspath):
                with open(abspath, encoding="utf-8") as f:
                    content = f.read()
            sources.append(f"#### {relpath}\n```python\n{content[:2500]}\n```")
        sources_block = "\n\n".join(sources) if sources else "(no source files found)"

        last_error_log = {}
        try:
            with get_db_cursor(commit=False) as cursor:
                cursor.execute("""
                    SELECT * FROM scraper_execution_logs
                    WHERE bundle_name = %s AND (status = 'ZERO_ROWS' OR status = 'FAILED' OR status = 'DEGRADED')
                    ORDER BY created_at DESC LIMIT 1;
                """, (bundle_name,))
                row = cursor.fetchone()
                if row:
                    last_error_log = dict(row)
        except Exception as e:
            logger.error(f"Error fetching failure log for '{bundle_name}': {e}")

        product_context = self.load_product_context()

        prompt = f"""
================================================================================
🤖 AI SCRAPER AUTO-REMEDIATION PROMPT FOR BUNDLE: '{bundle_name}'
================================================================================

### 📋 PRODUCT & ARCHITECTURE CONTEXT (AGENTS.md):
{product_context[:1200]}... [Truncated for brevity]

### 🚨 FAILURE DIAGNOSTICS FOR '{bundle_name}':
- Status: {last_error_log.get('status') or 'UNKNOWN'}
- Items Scraped: {last_error_log.get('items_scraped', 0)}
- HTTP 403 (Bans): {last_error_log.get('http_403_count', 0)}
- HTTP 429 (Limits): {last_error_log.get('http_429_count', 0)}
- Error Message: {last_error_log.get('error_message') or 'No failure log in scraper_execution_logs.'}

### 📄 CURRENT SOURCE (scraper.py + every declared extractor.py — a ZERO_ROWS /
selector-drift failure is usually in an extractor.py, not scraper.py):
{sources_block}

### 💡 INSTRUCTIONS FOR AI AGENT:
1. Diagnose which file(s) above actually need to change to fix the failure. Selector
   drift (a ZERO_ROWS result with an unchanged fetch path) means an extractor.py needs
   fixing, not scraper.py.
2. For EACH file you change, output one block in exactly this format — complete
   replacement content, no partial diffs, no files you are not changing:

### FILE: <path exactly as shown above>
```python
<complete new file content>
```
================================================================================
"""
        return {
            "bundle_name": bundle_name,
            "status": last_error_log.get("status") or "UNKNOWN",
            "error_message": last_error_log.get("error_message"),
            "ai_prompt": prompt,
            "scraper_path": scraper_path,
            "candidate_files": candidate_files,
        }

    def get_compressed_diagnostic_json(self, bundle_name: str) -> dict[str, Any]:
        """Compressed HAP diagnostic JSON from last failure log + scraper snippet.

        Does **not** include live HTML or extracted CSS selectors. Agents must
        read ``scraper.py`` / ``extractors/*/extractor.py`` and fetch a sample
        page when diagnosing selector drift.
        """
        bundle_dir = os.path.join(BUNDLES_DIR, bundle_name)
        scraper_path = os.path.join(bundle_dir, "scraper.py")
        extractor_hint = os.path.join(bundle_dir, "manifest.json")
        declared_extractors: list[str] = []
        if os.path.isfile(extractor_hint):
            try:
                with open(extractor_hint, encoding="utf-8") as f:
                    manifest = json.load(f)
                raw = (manifest.get("requirements") or {}).get("extractors") or []
                for item in raw:
                    if isinstance(item, str):
                        declared_extractors.append(item)
                    elif isinstance(item, dict) and item.get("name"):
                        declared_extractors.append(str(item["name"]))
            except Exception:
                declared_extractors = []

        diag = self.diagnose_bundle_failure(bundle_name)
        scraper_exists = os.path.isfile(scraper_path)
        scraper_code = ""
        if scraper_exists:
            with open(scraper_path, encoding="utf-8") as f:
                scraper_code = f.read()

        last_log = {}
        try:
            with get_db_cursor(commit=False) as cursor:
                cursor.execute(
                    """
                    SELECT status, items_scraped, http_200_count, http_403_count,
                           http_429_count, http_500_count, error_message, created_at
                    FROM scraper_execution_logs
                    WHERE bundle_name = %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (bundle_name,),
                )
                row = cursor.fetchone()
                if row:
                    last_log = _jsonable(dict(row))
        except Exception as e:
            logger.error("Error fetching last execution log for '%s': %s", bundle_name, e)
            last_log = {"error": str(e)}

        return {
            "protocol": "HAP/1.0",
            "bundle_name": bundle_name,
            "bundle_exists": os.path.isdir(bundle_dir),
            "scraper_exists": scraper_exists,
            "declared_extractors": declared_extractors,
            "status": last_log.get("status") or diag.get("status") or "UNKNOWN",
            "error_message": diag.get("error_message") or last_log.get("error_message"),
            "last_log": last_log,
            "target_file": f"bundles/{bundle_name}/scraper.py",
            "code_snippet": scraper_code[:CODE_SNIPPET_CHARS] if scraper_code else "",
            "missing_fields": [
                "failing_selectors",
                "html_sample",
            ],
            "instruction": (
                "HAP does not capture HTML or CSS selectors. Classify Mode A "
                "(ZERO_ROWS / selector drift in extractor.py), Mode B "
                "(HTTP 403/429 — fetch/proxy), or Mode C (Python exception). "
                "Apply a surgical edit; do not rewrite the bundle. "
                "Verify with `harbor agent-protocol test <bundle> --url <url>`, "
                "`harbor bundle validate`, and `harbor health`. "
                "`harbor agent-protocol patch` replaces the entire scraper.py."
            ),
        }

    def run_verification_test(
        self,
        bundle_name: str,
        *,
        url: str | None = None,
    ) -> dict[str, Any]:
        """Import the bundle scraper; optionally run one live scrape.

        Without ``url`` this only proves the module imports. That is not a
        scrape success. Live verification requires ``url``.
        """
        bundle_dir = os.path.join(BUNDLES_DIR, bundle_name)
        scraper_path = os.path.join(bundle_dir, "scraper.py")
        if not os.path.isdir(bundle_dir):
            return {
                "status": "FAILED",
                "phase": "lookup",
                "bundle_name": bundle_name,
                "error": f"Bundle '{bundle_name}' not found under bundles/.",
            }
        if not os.path.isfile(scraper_path):
            return {
                "status": "FAILED",
                "phase": "lookup",
                "bundle_name": bundle_name,
                "error": (
                    f"bundles/{bundle_name}/scraper.py is missing. "
                    "ETL/ML/catalog bundles have no scrape step — skip HAP test."
                ),
            }

        module_name = f"bundles.{bundle_name}.scraper"
        try:
            mod = self._fresh_module_import(module_name, scraper_path)
        except Exception as e:
            return {
                "status": "FAILED",
                "phase": "import",
                "bundle_name": bundle_name,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=8),
            }

        scrape_fn = self._resolve_scrape_callable(mod)
        if scrape_fn is None:
            return {
                "status": "FAILED",
                "phase": "import",
                "bundle_name": bundle_name,
                "error": f"{module_name} has no scrape() function or class method.",
            }

        if not url:
            return {
                "status": "IMPORT_OK",
                "phase": "import",
                "bundle_name": bundle_name,
                "live_scrape": False,
                "message": (
                    "scraper.py imported. This is not a scrape proof. "
                    "Re-run with --url for a live 1-page verification."
                ),
            }

        try:
            items = self._invoke_scrape(scrape_fn, url)
        except Exception as e:
            return {
                "status": "FAILED",
                "phase": "scrape",
                "bundle_name": bundle_name,
                "live_scrape": True,
                "url": url,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=8),
            }

        # A record only counts if it's a non-empty dict — [None], [{}], or ["oops"]
        # must not read as a working scrape just because the list itself is non-empty.
        valid_items = [it for it in items if isinstance(it, dict) and it] if isinstance(items, list) else []
        count = len(valid_items)
        status = "SUCCESS" if count else "ZERO_ROWS"
        result = {
            "status": status,
            "phase": "scrape",
            "bundle_name": bundle_name,
            "live_scrape": True,
            "url": url,
            "items_scraped": count,
        }
        if isinstance(items, list) and len(items) != count:
            result["discarded_non_record_items"] = len(items) - count
        return result

    @staticmethod
    def _fresh_module_import(module_name: str, file_path: str) -> Any:
        """Execute ``file_path`` as a brand-new module object, every call.

        Deliberately not ``importlib.reload()``: reload() re-executes the source into
        the *same* module namespace, so a name the new source removed (a function, an
        import) can still be found via the module's stale __dict__ from the previous
        version — a verification pass could resolve/call something that no longer
        exists in the file it's supposed to be testing. A fresh module object has no
        prior state to leak from.
        """
        spec = importlib.util.spec_from_file_location(f"{module_name}__hap_verify", file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load a module spec for '{file_path}'.")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _resolve_scrape_callable(mod: Any) -> Any | None:
        scrape = getattr(mod, "scrape", None)
        if callable(scrape) and not inspect.isclass(scrape):
            return scrape
        for obj in vars(mod).values():
            if (
                inspect.isclass(obj)
                and obj.__module__ == mod.__name__
                and callable(getattr(obj, "scrape", None))
            ):
                try:
                    return obj().scrape
                except TypeError:
                    continue
        return None

    @staticmethod
    def _invoke_scrape(scrape_fn: Any, url: str) -> Any:
        sig = inspect.signature(scrape_fn)
        params = [
            p
            for p in sig.parameters.values()
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        ]
        if not params:
            return scrape_fn()
        first = params[0].name
        try:
            return scrape_fn(**{first: url})
        except TypeError:
            return scrape_fn(url)

    def autofix_bundle_scraper(self, bundle_name: str, *, verify_url: str | None = None) -> dict[str, Any]:
        """Query the LLM, AST-validate, apply the patch(es), then verify they work.

        Candidate files are scraper.py plus every extractor.py the bundle declares —
        selector drift usually lives in an extractor, not scraper.py, so a fix limited
        to scraper.py alone can't address that failure mode (see AGENTS.md).

        Without ``verify_url`` this only proves the patched module(s) import cleanly —
        strictly more than AST validation, but not a scrape proof. With ``verify_url``
        it runs one live scrape against that URL; on failure it retries once with the
        failure fed back to the model. Whatever happens — LLM failure, AST failure,
        write failure, or verification failure on either attempt — every file this
        call touched is restored to its pre-patch content before returning FAILED.
        Only a verified SUCCESS leaves patched files in place.
        """
        diag = self.diagnose_bundle_failure(bundle_name)
        candidate_files: dict[str, str] = diag["candidate_files"]
        if not candidate_files:
            return {
                "status": "FAILED",
                "message": f"No patchable files found for bundle '{bundle_name}' (no scraper.py, no declared extractors).",
            }

        previous_contents: dict[str, str] = {}
        for relpath, abspath in candidate_files.items():
            try:
                with open(abspath, encoding="utf-8") as f:
                    previous_contents[relpath] = f.read()
            except OSError as e:
                return {"status": "FAILED", "message": f"Could not read '{relpath}' before patching: {e}"}

        prompt = diag["ai_prompt"]
        verification: dict[str, Any] = {}
        request_failure: dict[str, Any] | None = None
        patched_files: list[str] = []

        for attempt in (1, 2):
            print(f"🤖 Querying LLM Provider ({self.gateway.provider}) — attempt {attempt}/2...")
            response_text = self.gateway.query_provider(prompt)
            if not response_text:
                request_failure = {
                    "status": "FAILED",
                    "message": f"No response received from LLM provider '{self.gateway.provider}'. Check API key in .env.",
                }
                break

            raw_patches = self.extract_file_patches(response_text)
            if "" in raw_patches:
                # Legacy single-block response (no FILE marker) -> the bundle's scraper.py.
                legacy_code = raw_patches.pop("")
                primary = f"bundles/{bundle_name}/scraper.py"
                if primary in candidate_files:
                    raw_patches[primary] = legacy_code

            patches = {p: code for p, code in raw_patches.items() if p in candidate_files}
            ignored = sorted(set(raw_patches) - set(patches))
            if ignored:
                logger.warning(f"Ignoring patch for undeclared file(s) (not offered to the model): {ignored}")

            if not patches:
                request_failure = {
                    "status": "FAILED",
                    "message": "Model response contained no patch for a known file (scraper.py or a declared extractor.py).",
                }
                break

            ast_errors = [
                f"{relpath}: {msg}"
                for relpath, code in patches.items()
                for is_valid, msg in [self.validate_python_ast(code)]
                if not is_valid
            ]
            if ast_errors:
                request_failure = {
                    "status": "FAILED",
                    "message": "Generated code failed AST validation: " + "; ".join(ast_errors),
                }
                break

            try:
                for relpath, code in patches.items():
                    abspath = candidate_files[relpath]
                    with open(f"{abspath}.bak", "w", encoding="utf-8") as f:
                        f.write(previous_contents[relpath])
                    with open(abspath, "w", encoding="utf-8") as f:
                        f.write(code)
                    if relpath not in patched_files:
                        patched_files.append(relpath)
            except Exception as e:
                request_failure = {"status": "FAILED", "message": f"Failed writing patch to disk: {e}"}
                break

            print(
                f"🧪 Verifying patch to {', '.join(sorted(patches))} "
                f"({'live scrape against ' + verify_url if verify_url else 'import only'})..."
            )
            verification = self.run_verification_test(bundle_name, url=verify_url)
            if verification.get("status") in {"SUCCESS", "IMPORT_OK"}:
                logger.info(f"Applied and verified AI patch to {sorted(patches)}.")
                note = "" if verify_url else " (import-only — pass --url for a live scrape proof)"
                return {
                    "status": "SUCCESS",
                    "message": (
                        f"Successfully auto-remediated '{bundle_name}'! Patched {', '.join(sorted(patches))}. "
                        f"AST validation + verification ({verification['status']}) passed{note}."
                    ),
                    "provider": self.gateway.provider,
                    "patched_files": sorted(patches),
                    "verification": verification,
                }

            if attempt == 1 and verify_url:
                logger.warning(f"Patch attempt 1 failed verification: {verification}. Retrying with feedback.")
                changed_src = "\n\n".join(f"#### {p}\n```python\n{c}\n```" for p, c in patches.items())
                prompt = (
                    f"{diag['ai_prompt']}\n\n"
                    "### ⚠️ PREVIOUS ATTEMPT FAILED VERIFICATION\n"
                    f"You changed these file(s) and they were tested against {verify_url!r}, result:\n"
                    f"{json.dumps(verification, default=str)}\n\n"
                    f"Here is what you changed:\n{changed_src}\n\n"
                    "Fix it. Use the same '### FILE: <path>' format for each file you change."
                )
                continue
            break

        # Whatever failed — restore every file this call touched to its pre-patch content.
        rollback_errors = []
        for relpath in patched_files:
            try:
                with open(candidate_files[relpath], "w", encoding="utf-8") as f:
                    f.write(previous_contents[relpath])
            except Exception as e:
                rollback_errors.append(f"{relpath}: {e}")

        if rollback_errors:
            return {
                "status": "FAILED",
                "message": (
                    "Patch failed and automatic rollback also failed for: "
                    + "; ".join(rollback_errors)
                    + ". Restore manually from the matching '.bak' files."
                ),
                "verification": verification,
            }

        if request_failure:
            suffix = f" Rolled back {', '.join(patched_files)} to its pre-patch version." if patched_files else ""
            return {"status": "FAILED", "message": f"{request_failure['message']}{suffix}", "verification": verification or None}

        return {
            "status": "FAILED",
            "message": (
                f"Patch failed verification ({verification.get('status')}) after "
                f"{'2 attempts' if verify_url else '1 attempt'}. Rolled back {', '.join(patched_files)}."
            ),
            "verification": verification,
        }

if __name__ == "__main__":
    engine = AIRemediatorEngine()
    print("Testing AIRemediatorEngine initialization...")
    diag = engine.diagnose_bundle_failure("demo_bundle")
    print(diag["ai_prompt"][:500])
