# Playwright MCP Automation

## Overview

The Playwright MCP (Model Context Protocol) Automation feature allows you to execute browser automation tasks using **plain text instructions**. Simply describe what you want to do in natural language, and the AI will interpret your instructions and execute them using Playwright.

## Key Features

✅ **Natural Language Processing**: Write automation instructions in plain English  
✅ **AI-Powered Interpretation**: Google Gemini 2.0 Flash converts text to Playwright actions  
✅ **Visual Execution**: Browser runs in visible mode so you can watch the automation  
✅ **Comprehensive Reporting**: Detailed execution reports with screenshots at each step  
✅ **Pass/Fail Indicators**: Each step shows success or failure status  
✅ **Screenshot Viewer**: Modal viewer with download capability for all screenshots  
✅ **Timeline View**: Visual step-by-step execution timeline with metrics  

## How It Works

### 1. **Instruction Interpretation**
   - User provides plain text instructions
   - Google Gemini 2.0 Flash parses the instruction
   - AI generates structured Playwright action objects
   - Actions include: navigate, click, fill, select, press, wait, screenshot, getText, getAttribute

### 2. **Action Execution**
   - Playwright browser launches in visible mode
   - Each action is executed sequentially
   - Screenshots captured after each step
   - Errors are caught and recorded
   - Execution continues even if a step fails

### 3. **Results Display**
   - Summary card shows overall status, total steps, success/fail counts, duration
   - Timeline displays each step with pass/fail badges
   - View screenshots for any step
   - Download screenshots with timestamps
   - Final screenshot of end state

## Supported Actions

### Navigation
```
navigate: Go to a URL
Example: "Go to google.com"
```

### Interaction
```
click: Click an element
fill: Fill an input field
select: Select dropdown option
press: Press keyboard key
Example: "Click the login button", "Fill username with 'test@example.com'"
```

### Waiting
```
wait: Wait for milliseconds
waitForSelector: Wait for element to appear
Example: "Wait for 2 seconds", "Wait for the results to load"
```

### Data Extraction
```
getText: Get text content from element
getAttribute: Get element attribute value
Example: "Get the title text", "Get the href attribute"
```

### Screenshot
```
screenshot: Capture current page state
Example: "Take a screenshot of the search results"
```

## Example Instructions

### Simple Examples
```
Go to amazon.com, search for 'laptop', and take a screenshot of the results
```

```
Navigate to github.com, click on 'Sign in', and capture the login page
```

```
Open youtube.com, search for 'playwright tutorial', and click the first video
```

### Complex Examples
```
Go to reddit.com, click on 'Popular', scroll down, and take screenshots of the top posts
```

```
Navigate to linkedin.com, fill in username with 'test@example.com', fill in password with 'test123', click login, and capture the homepage
```

```
Open google.com, search for 'weather in New York', wait for results, and get the temperature text
```

## API Endpoint

### `/api/playwright-mcp/execute`

**Method**: POST  
**Content-Type**: application/json

**Request Body**:
```json
{
  "instruction": "Go to google.com and search for 'playwright automation'"
}
```

**Response**:
```json
{
  "success": true,
  "execution_report": {
    "instruction": "Go to google.com and search for 'playwright automation'",
    "start_time": 1234567890.123,
    "end_time": 1234567895.456,
    "duration_seconds": 5.33,
    "success": true,
    "final_url": "https://www.google.com/search?q=playwright+automation",
    "steps": [
      {
        "step_number": 1,
        "action": "navigate",
        "description": "Navigate to Google",
        "url": "https://google.com",
        "result": "Navigated to https://google.com",
        "screenshot": "base64_encoded_image...",
        "duration_ms": 1234,
        "success": true
      },
      {
        "step_number": 2,
        "action": "fill",
        "description": "Search for playwright",
        "selector": "input[name='q']",
        "value": "playwright automation",
        "url": "https://google.com",
        "result": "Filled input[name='q'] with 'playwright automation'",
        "screenshot": "base64_encoded_image...",
        "duration_ms": 567,
        "success": true
      }
    ],
    "screenshots": [],
    "errors": [],
    "final_screenshot": "base64_encoded_image..."
  }
}
```

## Execution Report Structure

### Summary Metrics
- **Status**: Overall success or failure
- **Total Steps**: Number of actions executed
- **Success/Failed**: Count of successful vs failed steps
- **Duration**: Total execution time in seconds

### Step Details
Each step includes:
- **Step Number**: Sequential step identifier
- **Action**: Type of action (navigate, click, fill, etc.)
- **Description**: Human-readable description
- **Selector**: CSS selector (if applicable)
- **Value**: Input value or key press (if applicable)
- **URL**: Current page URL after action
- **Result**: Action result message
- **Screenshot**: Base64-encoded PNG image
- **Duration**: Step execution time in milliseconds
- **Success**: Boolean indicating success or failure
- **Error**: Error message (if failed)

## Technical Architecture

### Backend (app.py)

#### Route: `/playwright-mcp-automation`
- Renders the HTML template
- Sets active tab to `playwright-mcp`

#### Route: `/api/playwright-mcp/execute`
- Accepts POST requests with instruction
- Uses Google Gemini 2.0 Flash for AI interpretation
- Launches Playwright browser in visible mode
- Executes actions sequentially
- Captures screenshots at each step
- Returns comprehensive execution report

### Frontend (playwright-mcp-automation.html)

#### UI Components
- **Header Section**: Gradient hero with title and description
- **Input Section**: Textarea for instructions with examples
- **Action Buttons**: Execute and Clear buttons
- **Loading Overlay**: Spinner during execution
- **Results Section**: Summary cards and timeline
- **Screenshot Modal**: Full-screen image viewer with download

#### JavaScript Functions
- `executeAutomation()`: Sends instruction to API and displays results
- `displayResults(report)`: Renders execution report with timeline
- `showScreenshot(index)`: Opens modal for step screenshot
- `showFinalScreenshot()`: Opens modal for final screenshot
- `downloadScreenshot()`: Downloads screenshot with timestamp
- `clearInput()`: Clears instruction textarea
- `startNewAutomation()`: Resets UI for new automation

### AI Interpretation

#### Prompt Engineering
The AI prompt instructs Google Gemini to:
1. Parse plain text instruction
2. Generate structured JSON array of actions
3. Include action type, selector, value, URL, description
4. Follow Playwright best practices
5. Return only JSON (no markdown)

#### Action Mapping
```javascript
navigate → page.goto(url)
click → page.click(selector)
fill → page.fill(selector, value)
select → page.select_option(selector, value)
press → page.press(selector, key)
wait → time.sleep(ms / 1000)
waitForSelector → page.wait_for_selector(selector)
screenshot → page.screenshot()
getText → page.locator(selector).inner_text()
getAttribute → page.locator(selector).get_attribute(attr)
```

## Configuration

### Environment Variables
- `GOOGLE_API_KEY`: Required for Google Gemini API access

### Browser Settings
- **Viewport**: 1440x900
- **Headless**: False (visible mode)
- **Args**: `['--start-maximized']`

### Timeouts
- **Navigation**: 30 seconds
- **Element Actions**: 10 seconds
- **Screenshot**: No timeout

## Error Handling

### Step-Level Errors
- Errors are caught per step
- Error message recorded in execution report
- Execution continues to next step
- Failed steps marked with red badge and border

### Request-Level Errors
- Missing instruction returns 400 error
- API failures return 500 error with details
- Browser cleanup always executed in finally block

## Best Practices

### Writing Instructions

✅ **DO**:
- Be specific about URLs: "Go to google.com"
- Use clear action verbs: "Click", "Fill", "Search"
- Include descriptive context: "Fill username with 'test@example.com'"
- Specify wait conditions: "Wait for results to load"

❌ **DON'T**:
- Use vague instructions: "Do something on Google"
- Omit important details: "Search for something"
- Assume context: "Click the button" (which button?)
- Chain too many actions in one instruction

### Selector Strategies
The AI automatically generates selectors based on:
- Element names
- IDs and classes
- ARIA labels
- Text content
- Common patterns (e.g., search inputs, buttons)

### Performance Optimization
- Keep instructions focused and concise
- Avoid unnecessary waits
- Use specific selectors when possible
- Minimize screenshot requests for faster execution

## Troubleshooting

### Common Issues

#### Issue: "No instruction provided"
**Solution**: Ensure textarea is not empty before clicking Execute

#### Issue: "Element not found"
**Solution**: 
- Check if page has loaded completely
- Verify selector is correct
- Add wait before action: "Wait 2 seconds, then click..."

#### Issue: "Navigation timeout"
**Solution**:
- Check URL is valid and accessible
- Increase timeout or use simpler instruction
- Verify internet connection

#### Issue: "AI generates wrong actions"
**Solution**:
- Rewrite instruction with more specific details
- Break complex tasks into separate automations
- Use exact element names or IDs if known

### Debug Mode
Check browser console and Python console for:
- Step-by-step execution logs (🎭, 📍, ✅, ❌ emojis)
- AI interpretation results
- Playwright action details
- Error stack traces

## Future Enhancements

### Planned Features
- [ ] Multi-page automation support
- [ ] Assertions and validations
- [ ] Data extraction to CSV/JSON
- [ ] Scheduling and cron jobs
- [ ] Test case generation from automation
- [ ] Integration with CI/CD pipelines
- [ ] Video recording of execution
- [ ] Performance metrics (LCP, FID, CLS)
- [ ] A/B testing scenarios
- [ ] Mobile device emulation

### API Extensions
- [ ] Batch execution endpoint
- [ ] Webhook notifications
- [ ] Real-time execution streaming
- [ ] Action templates library
- [ ] Custom action plugins

## Security Considerations

### Current Implementation
- Browser runs locally on server
- No external data storage
- Screenshots in memory only
- Cleanup after each execution

### Recommendations for Production
- Implement authentication and authorization
- Rate limiting on API endpoint
- Input validation and sanitization
- Sandbox browser execution
- Encrypted screenshot storage
- Audit logging of all automations

## Performance Metrics

### Typical Execution Times
- Simple navigation: 1-3 seconds
- Form filling: 2-5 seconds
- Search and click: 3-8 seconds
- Complex multi-step: 10-30 seconds

### Resource Usage
- Memory: ~200-400 MB per browser instance
- CPU: Moderate during execution, idle when waiting
- Network: Depends on pages visited

## Comparison with Google Computer Use

| Feature | Playwright MCP | Google Computer Use |
|---------|---------------|---------------------|
| **AI Model** | Gemini 2.0 Flash | Gemini 2.5 Computer Use |
| **Execution** | Playwright actions | Screenshot-based |
| **Speed** | Fast (direct API) | Slower (vision processing) |
| **Accuracy** | High (CSS selectors) | Variable (OCR/vision) |
| **Cost** | Low (Flash model) | Free (preview model) |
| **Flexibility** | Playwright-specific | Any GUI application |
| **Debugging** | Clear step logs | Screenshot comparison |
| **Best For** | Web automation | General computer tasks |

## Conclusion

Playwright MCP Automation combines the power of AI language understanding with the precision of Playwright browser automation. It's perfect for:
- Quick testing and validation
- Automated data extraction
- UI/UX testing
- Regression testing
- Demo and presentation automation

The natural language interface makes browser automation accessible to everyone, from QA engineers to business analysts, without requiring coding expertise.

---

**Created**: January 2025  
**Last Updated**: January 2025  
**Version**: 1.0.0  
**Author**: Co-Tester Development Team
