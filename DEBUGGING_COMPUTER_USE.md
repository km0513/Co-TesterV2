# Google Computer Use - Troubleshooting & Debugging Guide

## Overview

This guide helps debug issues with the Google Computer Use implementation.

---

## ✅ Quick Checklist

Before testing, verify:

- [ ] Flask app is running (`python app.py`)
- [ ] `GOOGLE_API_KEY` is set in `.env` file
- [ ] `google-genai` package installed (`pip install google-genai`)
- [ ] `playwright` installed (`pip install playwright`)
- [ ] Chromium browser installed (`playwright install chromium`)

---

## 🔍 Common Issues

### 1. "No browser launches"

**Symptom**: You click "Run AI Agent" but no browser window appears.

**Root Cause**: Browser was in `headless=True` mode (invisible).

**Fix Applied**: Changed to `headless=False` in `app.py`:
```python
browser = playwright.chromium.launch(
    headless=False,  # Browser will be visible!
    args=['--start-maximized']
)
```

**Verify**:
1. Stop Flask app (Ctrl+C)
2. Restart: `python app.py`
3. Try automation - you SHOULD see a browser window now

---

### 2. "Import errors for google.genai"

**Symptom**: 
```
ImportError: No module named 'google.genai'
```

**Fix**:
```bash
pip install google-genai
```

**Verify**:
```bash
python -c "from google import genai; print('✅ Works!')"
```

---

### 3. "GOOGLE_API_KEY not found"

**Symptom**:
```
Error: API key is required
```

**Fix**:
1. Create/edit `.env` file:
```bash
GOOGLE_API_KEY=your-actual-api-key-here
```

2. Get your API key: https://aistudio.google.com/apikey

3. Restart Flask app

---

### 4. "Playwright/Chromium not found"

**Symptom**:
```
Error: Executable doesn't exist
```

**Fix**:
```bash
pip install playwright
playwright install chromium
```

**Verify**:
```bash
playwright --version
```

---

### 5. "Timeout errors"

**Symptom**:
```
Error executing navigate: Timeout 30000ms exceeded
```

**Fix**: Already implemented in code with:
- 30 second timeouts
- Graceful fallback on timeout
- Non-critical waits

**If still occurring**:
- Check your internet connection
- Try simpler instructions first
- Check Flask console for detailed logs

---

## 🧪 Testing Steps

### Step 1: Verify Imports
```bash
python -c "from google import genai; from google.genai import types; from playwright.sync_api import sync_playwright; print('✅ All imports work!')"
```

### Step 2: Verify API Key
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('GOOGLE_API_KEY:', 'SET' if os.getenv('GOOGLE_API_KEY') else 'NOT SET')"
```

### Step 3: Test Simple Request
```bash
# Make sure Flask is running first!
python test_simple_computeruse.py
```

Expected output:
- ✅ Browser window opens (visible!)
- ✅ Navigates to google.com
- ✅ Returns success response

---

## 📊 What You Should See

### In Browser (Visible Window):
1. Chrome/Chromium window opens
2. Navigates to google.com
3. Performs actions as instructed
4. Window closes when done

### In Flask Console:
```
🚀 Starting Computer Use automation for: Go to google.com
✅ Browser launched successfully
🌐 Navigating to initial page...
✅ Loaded: https://www.google.com
🤖 Configuring Gemini 2.5 Computer Use...
📸 Capturing initial screenshot...
✅ Screenshot captured (234567 bytes)
🔄 Starting agent loop (max 10 turns)...

--- Turn 1/10 ---
🧠 Asking Gemini 2.5 Computer Use for next action...
✅ Got response from Gemini
📋 Function calls to execute: 1
⚡ Executing actions...
  🎬 Action: navigate | Args: {'url': 'https://www.google.com'}
  🌐 Navigating to: https://www.google.com
  ✅ Navigated to: https://www.google.com/
✅ Executed 1 actions
📸 Capturing feedback screenshot...
✅ Got 1 function responses

--- Turn 2/10 ---
🧠 Asking Gemini 2.5 Computer Use for next action...
✅ Got response from Gemini
✅ Task complete! Result: I have navigated to Google.com
🎉 Task completed successfully!
📊 Steps executed: 2
🌐 Final URL: https://www.google.com/
💬 Result: I have navigated to Google.com
🧹 Cleaning up browser...
✅ Cleanup complete
```

### In Browser UI (Your webpage):
```
✅ Success
Task completed in 2 steps
Final URL: https://www.google.com/
```

---

## 🐛 Debugging Tips

### Enable Maximum Logging

The code already has extensive logging! Check your Flask console for:
- 🚀 Startup messages
- 🌐 Navigation logs
- 🎬 Action execution logs
- 📸 Screenshot capture logs
- ✅ Success confirmations
- ❌ Error messages

### Check Specific Logs

**Problem**: "Nothing happens"
**Look for**: 
```
🚀 Starting Computer Use automation for: ...
```
If missing → Request not reaching endpoint

**Problem**: "Browser doesn't open"
**Look for**:
```
✅ Browser launched successfully
```
If missing → Playwright issue

**Problem**: "Gemini not responding"
**Look for**:
```
🧠 Asking Gemini 2.5 Computer Use for next action...
✅ Got response from Gemini
```
If timeout → API key or network issue

---

## 🔧 Advanced Debugging

### Test Playwright Directly
```python
from playwright.sync_api import sync_playwright

playwright = sync_playwright().start()
browser = playwright.chromium.launch(headless=False)
page = browser.new_page()
page.goto("https://google.com")
print(f"✅ Browser working! URL: {page.url}")
input("Press Enter to close...")
browser.close()
playwright.stop()
```

### Test Google GenAI Directly
```python
from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

response = client.models.generate_content(
    model='gemini-2.0-flash-exp',
    contents='Say hello!'
)

print(f"✅ Gemini works! Response: {response.text}")
```

### Test Computer Use Tool
```python
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

config = types.GenerateContentConfig(
    tools=[types.Tool(
        computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER
        )
    )],
)

response = client.models.generate_content(
    model='gemini-2.5-computer-use-preview-10-2025',
    contents='Navigate to google.com',
    config=config,
)

print(f"✅ Computer Use tool works!")
print(f"Response: {response}")
```

---

## 📝 Implementation Details

### Key Changes Made

1. **Visible Browser** (was invisible):
```python
# OLD:
browser = playwright.chromium.launch(headless=True)

# NEW:
browser = playwright.chromium.launch(
    headless=False,  # Visible!
    args=['--start-maximized']
)
```

2. **Extensive Logging** (was minimal):
- Added 20+ log statements
- Shows every step of execution
- Helps identify exactly where issues occur

3. **Better Error Handling**:
- Graceful fallbacks on timeouts
- Continues execution when possible
- Detailed error messages

---

## 🎯 Expected Behavior

### Successful Run:

1. ✅ You click "Run AI Agent" in UI
2. ✅ Chrome/Chromium window opens (VISIBLE)
3. ✅ Browser navigates to google.com
4. ✅ AI decides what actions to take
5. ✅ Actions execute (click, type, navigate)
6. ✅ Screenshot captured after each action
7. ✅ AI sees screenshot and decides next step
8. ✅ Loop continues until task complete
9. ✅ Browser closes
10. ✅ Result shown in UI

### Failed Run Indicators:

❌ **No "🚀 Starting..." log** → Request not reaching endpoint
❌ **No browser window** → Playwright issue or headless=True
❌ **Browser opens then closes** → Error in execution (check logs)
❌ **Timeout errors** → Network or slow page (should continue anyway)
❌ **API errors** → GOOGLE_API_KEY issue

---

## 🚨 If Still Not Working

### Collect Diagnostics:

```bash
# 1. Check Python version
python --version
# Should be 3.8+

# 2. Check packages
pip list | grep -E "google-genai|playwright"

# 3. Check Playwright
playwright --version

# 4. Check environment
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key:', 'SET' if os.getenv('GOOGLE_API_KEY') else 'MISSING')"

# 5. Check Flask
curl http://localhost:5000/
# Should return something
```

### Share This Info:

1. Python version
2. OS (Windows/Mac/Linux)
3. Package versions
4. Complete Flask console output
5. Browser console errors (F12)
6. Any error messages

---

## ✅ Success Criteria

You'll know it's working when:

1. ✅ Browser window opens (you can see it!)
2. ✅ Flask console shows detailed logs
3. ✅ Browser performs actions automatically
4. ✅ UI shows success message with results
5. ✅ No errors in Flask console

---

## 📞 Still Stuck?

If you've tried everything above:

1. **Check Flask console** - look for red error messages
2. **Check browser console** (F12) - look for network errors  
3. **Try simplest possible instruction**: "Go to google.com"
4. **Restart everything**: Kill Flask, restart, try again
5. **Check API quota**: https://aistudio.google.com/apikey

---

**Result**: With `headless=False` and extensive logging, you should now see exactly what's happening! 🎉
