# Playwright Wait Injection

## Overview
The Automation Test Creator automatically enhances Playwright code with stability waits to prevent flaky tests.

## Transformations Applied

### 1. Page Load Waits
**Before:**
```python
page.goto("https://example.com")
page.locator("#button").click()
```

**After:**
```python
page.goto("https://example.com")
page.wait_for_load_state("networkidle")  # Wait for network to be idle
page.locator("#button").click()
```

### 2. Element Visibility Waits (Click)
**Before:**
```python
page.locator("#submit-button").click()
```

**After:**
```python
page.locator("#submit-button").wait_for(state="visible", timeout=10000)  # Wait 10s for element
page.locator("#submit-button").click()
```

### 3. Element Visibility Waits (Fill)
**Before:**
```python
page.locator("#username").fill("testuser")
```

**After:**
```python
page.locator("#username").wait_for(state="visible", timeout=10000)  # Wait 10s for element
page.locator("#username").fill("testuser")
```

### 4. Default Timeout Configuration
**Before:**
```python
page = context.new_page()
```

**After:**
```python
page = context.new_page()
page.set_default_timeout(30000)  # 30 second default timeout
```

**Before:**
```python
context = browser.new_context()
```

**After:**
```python
context = browser.new_context()
context.set_default_timeout(30000)  # 30 second default timeout
```

## Benefits

1. **Prevents Race Conditions** - Waits for elements to be ready before interaction
2. **Handles Slow Networks** - networkidle wait ensures page is fully loaded
3. **Reduces Flaky Tests** - Explicit waits reduce timing-related failures
4. **Better Debugging** - Clear timeout errors instead of cryptic "element not found"
5. **Production-Ready** - Code works in various network conditions

## When Applied

The wait injection is applied:
- ✅ When generating with AI (`/api/automation-test-creator/generate-with-ai`)
- ✅ When executing tests (`/api/automation-test-creator/execute`)
- ✅ In downloaded ZIP packages
- ✅ In Jira exports

## Configuration

Default timeouts:
- **Element waits**: 10 seconds (10000ms)
- **Page/Context timeout**: 30 seconds (30000ms)
- **Load state**: networkidle

These can be adjusted in the `add_waits_to_playwright_code()` function in `app.py`.

## Example: Full Transformation

**Original Playwright Codegen Output:**
```python
from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://example.com/login")
    page.locator("#username").fill("admin")
    page.locator("#password").fill("password123")
    page.locator("button[type='submit']").click()
    page.locator("h1").click()
    context.close()
    browser.close()

with sync_playwright() as playwright:
    run(playwright)
```

**Enhanced with Automatic Waits:**
```python
from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    context.set_default_timeout(30000)  # 30 second default timeout
    page = context.new_page()
    page.set_default_timeout(30000)  # 30 second default timeout
    page.goto("https://example.com/login")
    page.wait_for_load_state("networkidle")
    page.locator("#username").wait_for(state="visible", timeout=10000)
    page.locator("#username").fill("admin")
    page.locator("#password").wait_for(state="visible", timeout=10000)
    page.locator("#password").fill("password123")
    page.locator("button[type='submit']").wait_for(state="visible", timeout=10000)
    page.locator("button[type='submit']").click()
    page.locator("h1").wait_for(state="visible", timeout=10000)
    page.locator("h1").click()
    context.close()
    browser.close()

with sync_playwright() as playwright:
    run(playwright)
```

## Notes

- Waits are **only added if not already present** - won't duplicate existing waits
- Works with both `locator()` and `get_by_*()` methods
- Preserves original code indentation
- Logs transformation details for debugging
