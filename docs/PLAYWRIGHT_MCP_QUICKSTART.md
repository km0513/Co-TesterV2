# 🎭 Playwright MCP Automation - Quick Start

## What is it?

A new feature that lets you automate browser tasks using **plain text instructions**. No coding required!

## How to Use

1. **Navigate to Playwright MCP Automation**
   - Click on "Playwright MCP" in the left sidebar or top navbar

2. **Enter Your Instruction**
   ```
   Go to google.com, search for 'playwright tutorial', and take a screenshot
   ```

3. **Click "Execute Automation"**
   - Browser will open visibly
   - AI interprets your instruction
   - Actions execute automatically
   - Screenshots captured at each step

4. **View Results**
   - Summary card with metrics
   - Timeline with pass/fail status
   - Screenshots available for each step
   - Download capability

## Example Instructions

### Simple Web Tasks
```
Go to amazon.com and search for 'laptop'
```

```
Navigate to github.com and click on Sign in
```

```
Open youtube.com and search for 'python tutorial'
```

### Multi-Step Tasks
```
Go to reddit.com, click Popular, and take a screenshot
```

```
Navigate to google.com, search for 'weather', and capture results
```

```
Open linkedin.com, fill username with 'test@email.com', and screenshot the login page
```

## Key Features

✅ **Natural Language**: Write instructions in plain English  
✅ **AI-Powered**: Google Gemini 2.0 Flash interprets your commands  
✅ **Visual Execution**: Watch the browser work in real-time  
✅ **Detailed Reports**: See pass/fail status for each step  
✅ **Screenshots**: Capture and download images from any step  
✅ **Error Handling**: Execution continues even if steps fail  

## What Gets Generated

### Execution Report Includes:
- ✅ Overall success/failure status
- 📊 Total steps executed
- ⏱️ Duration in seconds
- 📸 Screenshots at each step
- 🌐 URL after each action
- ❌ Error messages if any step fails

### Each Step Shows:
- Step number and description
- Action type (navigate, click, fill, etc.)
- Pass/fail badge with color coding
- Duration in milliseconds
- Screenshot preview button
- Error details if failed

## Supported Actions

| Action | Description | Example |
|--------|-------------|---------|
| **navigate** | Go to URL | "Go to google.com" |
| **click** | Click element | "Click the search button" |
| **fill** | Fill input field | "Fill username with 'test@example.com'" |
| **select** | Select dropdown | "Select 'United States' from country dropdown" |
| **press** | Press keyboard key | "Press Enter" |
| **wait** | Wait milliseconds | "Wait 2 seconds" |
| **waitForSelector** | Wait for element | "Wait for results to load" |
| **screenshot** | Capture page | "Take a screenshot" |
| **getText** | Get element text | "Get the title text" |
| **getAttribute** | Get attribute | "Get the href attribute" |

## Tips for Best Results

### ✅ Good Instructions:
- "Go to google.com and search for 'playwright automation'"
- "Navigate to amazon.com, search for 'laptop', and click first result"
- "Open github.com, click Sign in, and take a screenshot"

### ❌ Avoid:
- Vague instructions: "Do something on Google"
- Missing details: "Search for something"
- Unclear targets: "Click the button" (which one?)

## Technical Details

### Backend
- **Endpoint**: `/api/playwright-mcp/execute`
- **AI Model**: Google Gemini 2.0 Flash (fast + accurate)
- **Browser**: Playwright Chromium (visible mode)
- **Viewport**: 1440x900
- **Timeouts**: 30s navigation, 10s actions

### Frontend
- **Framework**: Vanilla JavaScript + HTML5
- **Styling**: Modern glassmorphism design
- **Features**: Modal screenshot viewer, download capability
- **Responsive**: Works on desktop and tablet

### API Response
```json
{
  "success": true,
  "execution_report": {
    "instruction": "Your instruction here",
    "duration_seconds": 5.33,
    "steps": [...],
    "final_screenshot": "base64_image...",
    "success": true
  }
}
```

## Differences from Google Computer Use

| Feature | Playwright MCP | Google Computer Use |
|---------|---------------|---------------------|
| Speed | ⚡ Fast | 🐢 Slower |
| Method | Direct Playwright API | Screenshot + Vision |
| Accuracy | 🎯 High | 🔍 Variable |
| Cost | 💰 Low (Flash model) | 🆓 Free (preview) |
| Best For | Web automation | General desktop tasks |

## Use Cases

### Testing
- Quick regression tests
- UI validation
- Form filling tests
- Navigation testing

### Data Extraction
- Scraping search results
- Capturing pricing info
- Collecting product details
- Monitoring competitors

### Demos & Training
- Automated product demos
- Tutorial recordings
- Onboarding flows
- Feature showcases

### Monitoring
- Website uptime checks
- Login flow validation
- Shopping cart testing
- Checkout process monitoring

## Requirements

- **Python**: Flask, Playwright, Google Generative AI
- **Environment**: `GOOGLE_API_KEY` must be set
- **Browser**: Chromium (auto-installed by Playwright)
- **Internet**: Required for AI API and web navigation

## Troubleshooting

### "No instruction provided"
→ Fill the textarea before clicking Execute

### "Element not found"
→ Add wait time: "Wait 2 seconds, then click the button"

### "Navigation timeout"
→ Check URL is valid and accessible

### "AI generates wrong actions"
→ Be more specific in your instruction

## Next Steps

1. Try the example instructions
2. Create your own automation
3. View and download screenshots
4. Check the detailed execution report
5. Share your results!

---

**Documentation**: See `/docs/PLAYWRIGHT_MCP_AUTOMATION.md` for full details  
**Route**: `/playwright-mcp-automation`  
**API**: `/api/playwright-mcp/execute`  
**Version**: 1.0.0
