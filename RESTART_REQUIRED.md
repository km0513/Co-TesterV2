# Server Restart Required

## ⚠️ ACTION NEEDED: Restart Flask Server

The code fixes have been applied to `app.py`, but Flask is still running the **old code in memory**.

### To apply the fixes:

1. **Stop the Flask server** (Ctrl+C in the terminal running Flask)
2. **Start it again** with: `python app.py`
3. **Try the workflow again**

### What Was Fixed:

✅ **Smart function extraction** - Properly unwraps `run()` function body  
✅ **Trailing line cleanup** - Removes extra empty lines  
✅ **Better stop detection** - Stops at non-indented lines  
✅ **Success logging** - Confirms when extraction works  

### Expected Result After Restart:

**Before (nested - wrong):**
```python
def test_example(playwright: Playwright) -> None:
    import re
    from playwright.sync_api import ...
    
    def run(playwright: Playwright) -> None:  # ← Nested!
        browser = playwright.chromium.launch(headless=False)
```

**After (flat - correct):**
```python
def test_example(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
```

### After Restart, Test:

1. Import from Jira (IRA-70047)
2. Execute Test
3. Check server logs - should see: "Successfully extracted run() function body and wrapped in test_example()"
4. Test should execute without nested function errors

---

**Status**: Code fixed ✅ | Server restart needed ⏳
