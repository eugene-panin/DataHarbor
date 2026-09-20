import ast
import importlib
import inspect
import json
import logging
import os
import sys
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

    def __init__(self):
        self.provider = os.getenv("AI_REPAIR_PROVIDER", "gemini").lower()
        self.api_key = (
            os.getenv("AI_REPAIR_API_KEY") or 
            os.getenv("GEMINI_API_KEY") or 
            os.getenv("DEEPSEEK_API_KEY") or 
            os.getenv("OPENAI_API_KEY") or 
            os.getenv("ANTHROPIC_API_KEY") or ""
        )
        self.model = os.getenv("AI_REPAIR_MODEL", "gemini-1.5-flash")
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
            "model": self.model if self.provider == "openai" else "deepseek-chat",
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
            "model": self.model if "claude" in self.model else "claude-3-5-sonnet-20241022",
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
        model_name = self.model if self.model != "gemini-1.5-flash" else "qwen2.5-coder:7b"
        payload = {"model": model_name, "prompt": prompt, "stream": False}
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

    def diagnose_bundle_failure(self, bundle_name: str) -> dict[str, Any]:
        """Collects failure logs and builds AI remediation prompt."""
        scraper_path = os.path.join(BUNDLES_DIR, bundle_name, "scraper.py")
        scraper_code = ""
        if os.path.exists(scraper_path):
            with open(scraper_path, encoding="utf-8") as f:
                scraper_code = f.read()

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

### 📄 CURRENT SCRAPER SOURCE CODE (scraper.py):
```python
{scraper_code[:2500]}
```

### 💡 INSTRUCTIONS FOR AI AGENT:
1. Analyze the failure and provide complete replacement Python code for `bundles/{bundle_name}/scraper.py`.
2. Wrap the complete executable code inside a ```python ``` code block.
================================================================================
"""
        return {
            "bundle_name": bundle_name,
            "status": last_error_log.get("status") or "UNKNOWN",
            "error_message": last_error_log.get("error_message"),
            "ai_prompt": prompt,
            "scraper_path": scraper_path
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
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)
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

        count = len(items) if isinstance(items, list) else 0
        status = "SUCCESS" if count else "ZERO_ROWS"
        return {
            "status": status,
            "phase": "scrape",
            "bundle_name": bundle_name,
            "live_scrape": True,
            "url": url,
            "items_scraped": count,
        }

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

    def _request_patch(self, prompt: str) -> tuple[str | None, dict[str, Any] | None]:
        """Query the LLM and AST-validate the result. Returns (code, None) or (None, failure_dict)."""
        response_text = self.gateway.query_provider(prompt)
        if not response_text:
            return None, {
                "status": "FAILED",
                "message": f"No response received from LLM provider '{self.gateway.provider}'. Check API key in .env.",
            }
        extracted_code = self.extract_code_block(response_text)
        is_valid_ast, ast_msg = self.validate_python_ast(extracted_code)
        if not is_valid_ast:
            logger.error(f"Generated patch failed AST validation: {ast_msg}")
            return None, {"status": "FAILED", "message": f"Generated code failed AST validation: {ast_msg}"}
        return extracted_code, None

    def autofix_bundle_scraper(self, bundle_name: str, *, verify_url: str | None = None) -> dict[str, Any]:
        """Query the LLM, AST-validate, apply the patch, then verify it actually works.

        Without ``verify_url`` this only proves the patched module imports cleanly —
        strictly more than AST validation (catches bad references/attrs), but not a
        scrape proof. With ``verify_url`` it runs one live scrape against that URL;
        on failure it retries once with the failure fed back to the model, then
        rolls back to the pre-patch ``scraper.py`` rather than leaving a scraper that
        looks patched but doesn't work.
        """
        diag = self.diagnose_bundle_failure(bundle_name)
        scraper_path = diag["scraper_path"]

        try:
            with open(scraper_path, encoding="utf-8") as f:
                previous_code = f.read()
        except OSError as e:
            return {"status": "FAILED", "message": f"Could not read existing scraper before patching: {e}"}

        prompt = diag["ai_prompt"]
        verification: dict[str, Any] = {}

        for attempt in (1, 2):
            print(f"🤖 Querying LLM Provider ({self.gateway.provider}) — attempt {attempt}/2...")
            extracted_code, failure = self._request_patch(prompt)
            if failure:
                return failure

            backup_path = f"{scraper_path}.bak"
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(previous_code)
                with open(scraper_path, "w", encoding="utf-8") as f:
                    f.write(extracted_code)
            except Exception as e:
                return {"status": "FAILED", "message": f"Failed writing patch to disk: {e}"}

            print(f"🧪 Verifying patch ({'live scrape against ' + verify_url if verify_url else 'import only'})...")
            verification = self.run_verification_test(bundle_name, url=verify_url)
            if verification.get("status") in {"SUCCESS", "IMPORT_OK"}:
                logger.info(f"Applied and verified AI patch to '{scraper_path}' (previous version: '{backup_path}').")
                note = "" if verify_url else " (import-only — pass --url for a live scrape proof)"
                return {
                    "status": "SUCCESS",
                    "message": (
                        f"Successfully auto-remediated '{bundle_name}'! AST validation + verification "
                        f"({verification['status']}) passed{note}. Previous scraper.py saved to "
                        f"'{os.path.basename(backup_path)}'."
                    ),
                    "provider": self.gateway.provider,
                    "backup_path": backup_path,
                    "verification": verification,
                }

            if attempt == 1 and verify_url:
                logger.warning(f"Patch attempt 1 failed verification: {verification}. Retrying with feedback.")
                prompt = (
                    f"{diag['ai_prompt']}\n\n"
                    "### ⚠️ PREVIOUS ATTEMPT FAILED VERIFICATION\n"
                    f"Your last patch was applied and tested against {verify_url!r}, result:\n"
                    f"{json.dumps(verification, default=str)}\n\n"
                    "Here is the patch that failed:\n```python\n"
                    f"{extracted_code}\n```\n"
                    "Fix it and return the complete corrected scraper.py."
                )

        # Both attempts failed verification (or one attempt, when verify_url is unset) — roll back.
        try:
            with open(scraper_path, "w", encoding="utf-8") as f:
                f.write(previous_code)
        except Exception as e:
            return {
                "status": "FAILED",
                "message": f"Patch failed verification AND rollback failed: {e}. Manually restore from '{scraper_path}.bak'.",
                "verification": verification,
            }
        return {
            "status": "FAILED",
            "message": (
                f"Patch failed verification ({verification.get('status')}) after "
                f"{'2 attempts' if verify_url else '1 attempt'}. Rolled back to the original scraper.py."
            ),
            "verification": verification,
        }

if __name__ == "__main__":
    engine = AIRemediatorEngine()
    print("Testing AIRemediatorEngine initialization...")
    diag = engine.diagnose_bundle_failure("demo_bundle")
    print(diag["ai_prompt"][:500])
