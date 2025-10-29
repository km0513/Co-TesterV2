"""Utilities for generating and executing Playwright replays for Bug Builder sessions."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - Playwright may not be installed in some environments
    sync_playwright = None  # type: ignore
    PlaywrightTimeoutError = Exception  # type: ignore


@dataclass
class ReplayArtifactPaths:
    base_dir: str
    script_path: str
    trace_path: str
    video_dir: str
    video_path: Optional[str]


def ensure_replay_directories(root_dir: str, session_id: str) -> ReplayArtifactPaths:
    base_dir = os.path.join(root_dir, session_id)
    os.makedirs(base_dir, exist_ok=True)

    script_path = os.path.join(base_dir, "replay_script.py")
    trace_path = os.path.join(base_dir, "trace.zip")
    video_dir = os.path.join(base_dir, "videos")
    os.makedirs(video_dir, exist_ok=True)

    video_path = None
    if os.path.isdir(video_dir):
        existing = sorted(
            [
                os.path.join(video_dir, name)
                for name in os.listdir(video_dir)
                if name.endswith(".webm") or name.endswith(".mp4")
            ],
            key=os.path.getmtime,
        )
        if existing:
            video_path = existing[-1]

    return ReplayArtifactPaths(
        base_dir=base_dir,
        script_path=script_path,
        trace_path=trace_path,
        video_dir=video_dir,
        video_path=video_path,
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _build_selector(target: Optional[Dict[str, Any]]) -> Optional[str]:
    if not target:
        return None

    tag = (target.get("tagName") or "").lower()
    target_id = target.get("id") or target.get("elementId")
    data_testid = target.get("dataTestId") or target.get("data-testid")
    aria = target.get("ariaLabel") or target.get("aria-label")
    placeholder = target.get("placeholder")
    role = target.get("role")
    text = (target.get("text") or target.get("innerText") or "").strip()
    class_attr = target.get("className") or ""

    if data_testid:
        return f"[data-testid='{_escape(str(data_testid))}']"
    if target_id:
        return f"#{_escape(str(target_id))}"
    if role and text:
        return f"role={_escape(role)}[name='{_escape(text)}']"
    if aria:
        return f"[aria-label='{_escape(str(aria))}']"
    if placeholder:
        return f"input[placeholder='{_escape(str(placeholder))}']"
    if tag and text and len(text) <= 80:
        return f"text='{_escape(text)}'"
    if tag and class_attr:
        first_class = class_attr.split()[0]
        if first_class:
            return f"{tag}.{_escape(first_class)}"
    if tag:
        return tag
    return None


def _generate_action_code(action: Dict[str, Any]) -> Optional[str]:
    action_type = (action.get("type") or "").lower()
    url = action.get("url") or action.get("pageUrl")
    target = action.get("target") if isinstance(action.get("target"), dict) else None
    selector = _build_selector(target)

    if action_type in {"navigation", "goto"} and url:
        return f"page.goto('{_escape(str(url))}', wait_until='domcontentloaded')"
    if action_type == "click" and selector:
        return f"page.click(" + _selector_to_playwright(selector) + ")"
    if action_type in {"input", "change"} and selector:
        value = action.get("value") or ""
        return f"page.fill({_selector_to_playwright(selector)}, '{_escape(str(value))}')"
    if action_type == "keydown":
        key = action.get("key") or "Enter"
        return f"page.keyboard.press('{_escape(str(key))}')"
    if action_type == "wait":
        duration = action.get("duration", 500)
        return f"page.wait_for_timeout({int(duration)})"
    return None


def _selector_to_playwright(selector: str) -> str:
    if selector.startswith("role="):
        # Role selector format role=button[name='Submit']
        return f'"{selector}"'  # keep as string literal
    if selector.startswith("text="):
        return f'"{selector}"'
    if selector.startswith("#") or selector.startswith("["):
        return f"'{selector}'"
    return f"'{selector}'"


def generate_script_text(actions: List[Dict[str, Any]], artifacts: ReplayArtifactPaths) -> str:
    body_lines: List[str] = []
    for action in actions:
        code = _generate_action_code(action)
        if code:
            body_lines.append(f"        {code}")

    if not body_lines:
        body_lines.append("        page.wait_for_timeout(1000)")

    code_block = "\n".join(body_lines)

    return textwrap.dedent(
        f"""
        from playwright.sync_api import sync_playwright

        def run_replay():
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(record_video_dir=r"{artifacts.video_dir}")
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                try:
{code_block}
                finally:
                    context.tracing.stop(path=r"{artifacts.trace_path}")
                    context.close()
                    browser.close()

        if __name__ == '__main__':
            run_replay()
        """
    ).strip() + "\n"


def run_replay(actions: List[Dict[str, Any]], artifacts: ReplayArtifactPaths) -> Dict[str, Any]:
    if sync_playwright is None:
        return {
            "status": "failed",
            "error": "Playwright is not installed in this environment."
        }

    result: Dict[str, Any] = {"status": "success"}

    try:
        with sync_playwright() as p:  # type: ignore
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(record_video_dir=artifacts.video_dir)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()

            for action in actions:
                code = _generate_action_code(action)
                if not code:
                    continue
                action_type = (action.get("type") or "").lower()
                try:
                    if action_type in {"navigation", "goto"}:
                        page.goto(action.get("url") or action.get("pageUrl"), wait_until="domcontentloaded")
                    elif action_type == "click":
                        selector = _build_selector(action.get("target"))
                        if selector:
                            if selector.startswith("role="):
                                role_part = selector.split("[", 1)[0].split("=", 1)[1]
                                name_part = selector.split("name=", 1)[1].rstrip("]')") if "name=" in selector else None
                                locator = page.get_by_role(role_part, name=name_part) if name_part else page.get_by_role(role_part)
                                locator.click()
                            elif selector.startswith("text="):
                                locator = page.get_by_text(selector.split("=", 1)[1].strip("'\""))
                                locator.click()
                            else:
                                page.click(selector)
                    elif action_type in {"input", "change"}:
                        selector = _build_selector(action.get("target"))
                        if selector:
                            value = action.get("value") or ""
                            if selector.startswith("text="):
                                locator = page.get_by_text(selector.split("=", 1)[1].strip("'\""))
                                locator.fill(str(value))
                            else:
                                page.fill(selector, str(value))
                    elif action_type == "keydown":
                        key = action.get("key") or "Enter"
                        page.keyboard.press(str(key))
                    elif action_type == "wait":
                        duration = int(action.get("duration", 500))
                        page.wait_for_timeout(duration)
                except PlaywrightTimeoutError as time_err:
                    result.setdefault("warnings", []).append(
                        f"Timeout during {action_type}: {time_err}"
                    )
                except Exception as action_err:  # pragma: no cover - best effort logging
                    result.setdefault("warnings", []).append(
                        f"Failed to execute {action_type}: {action_err}"
                    )

            context.tracing.stop(path=artifacts.trace_path)
            context.close()
            browser.close()

        # Determine latest video file if generated
        videos = sorted(
            [
                os.path.join(artifacts.video_dir, f)
                for f in os.listdir(artifacts.video_dir)
                if f.endswith(".webm") or f.endswith(".mp4")
            ],
            key=os.path.getmtime,
        )
        if videos:
            result["video_path"] = videos[-1]

    except Exception as exc:  # pragma: no cover - runtime errors captured for caller
        result = {
            "status": "failed",
            "error": str(exc)
        }

    return result


def save_script(script_text: str, script_path: str) -> None:
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(script_text)


def summarize_actions(actions: List[Dict[str, Any]]) -> List[str]:
    summary = []
    for action in actions:
        action_type = (action.get("type") or "").lower()
        timestamp = action.get("timestamp")
        seconds = f"{(timestamp or 0) / 1000:.1f}s" if timestamp is not None else "n/a"
        target = action.get("target", {})
        desc = target.get("text") or target.get("ariaLabel") or target.get("placeholder") or target.get("id")
        if action_type in {"click", "input", "change"} and desc:
            summary.append(f"{seconds} – {action_type} on '{desc}'")
        elif action_type in {"navigation", "goto"}:
            summary.append(f"{seconds} – navigated to {action.get('url') or action.get('pageUrl')}")
    return summary
