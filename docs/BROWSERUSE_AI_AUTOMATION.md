# BrowserUse AI-Powered Automation - Technical Documentation

## Overview

The BrowserUse Automation feature in Co-Tester uses an **AI-powered Playwright Agent** from the BrowserUse library to intelligently execute browser automation tasks. Unlike traditional automation tools that require exact selectors and brittle scripts, this AI agent understands natural language descriptions and adapts to dynamic web pages.

## How It Works

### Architecture

```
User Interface (Steps) 
    ↓
Natural Language Conversion 
    ↓
BrowserUse AI Agent (Google Gemini)
    ↓
Playwright Browser Automation
    ↓
Execution Results & Reports
```

### Components

1. **Frontend (browseruse-automation-stepwise.html)**
   - User-friendly step builder interface
   - 26+ predefined action types organized by category
   - Real-time preview of automation scenario
   - Export/Import functionality for workflow reuse

2. **Backend (app.py - `/api/browseruse/navigation`)**
   - Receives structured steps from UI
   - Converts steps to natural language prompts
   - Creates BrowserUse Agent with Google Generative AI LLM
   - Executes automation asynchronously
   - Generates comprehensive reports with error handling

3. **AI Agent (BrowserUse Library)**
   - Uses Google Gemini 2.0 Flash Exp model
   - Interprets natural language automation tasks
   - Controls Playwright browser programmatically
   - Handles dynamic elements, waits, and page changes
   - Adapts to unexpected scenarios

## Step-to-Prompt Conversion

### Example Workflow

**User Creates Steps:**
```javascript
[
  { action: 'navigate', url: 'https://example.com' },
  { action: 'click', selector: '#login-button' },
  { action: 'fill', selector: '#username', value: 'testuser' },
  { action: 'assert_text', selector: '.welcome', text: 'Welcome' }
]
```

**Backend Converts to Natural Language:**
```python
prompt = '. '.join([step_to_description(step) for step in steps])
# Result: "Navigate to URL: https://example.com. Click element: #login-button. Fill form field: #username with testuser. Assert element contains text: .welcome 'Welcome'"
```

**AI Agent Executes:**
```python
agent = Agent(task=prompt, llm=llm)
result = asyncio.run(agent.run())
```

## Supported Actions (26+ Types)

### Navigation
- **navigate**: Navigate to URL
- **wait_for_navigation**: Wait for page navigation
- **wait_for_url**: Wait for specific URL
- **go_back**: Browser back button
- **go_forward**: Browser forward button
- **reload**: Refresh page

### Interactions
- **click**: Click element
- **double_click**: Double click
- **right_click**: Context menu click
- **hover**: Hover over element
- **focus**: Focus element
- **blur**: Remove focus

### Form Input
- **fill**: Fill text input
- **type**: Type text character by character
- **clear**: Clear input field
- **select**: Select dropdown option
- **check**: Check checkbox
- **uncheck**: Uncheck checkbox
- **upload_file**: Upload file

### Waits & Timing
- **wait_for_element**: Wait for element to appear
- **wait_for_timeout**: Wait for duration
- **wait_for_selector**: Wait for CSS selector

### Assertions
- **assert_visible**: Verify element visibility
- **assert_text**: Verify element text content
- **assert_url**: Verify current URL
- **assert_title**: Verify page title

### Data Extraction
- **extract_text**: Extract text from element
- **page_html**: Get full page HTML

### Advanced
- **press_key**: Press keyboard key
- **custom**: Custom AI instruction (free-form)

## AI Agent Features

### Intelligent Adaptation

The AI agent goes beyond simple script execution:

1. **Dynamic Element Handling**
   - Automatically waits for elements to load
   - Handles lazy-loaded content
   - Adapts to element position changes

2. **Context Understanding**
   - Interprets ambiguous selectors intelligently
   - Understands page structure and relationships
   - Makes smart decisions when multiple matches exist

3. **Error Recovery**
   - Retries failed actions with different strategies
   - Handles popups and modals automatically
   - Adapts to unexpected page states

4. **Natural Language Flexibility**
   - Accepts custom instructions via "custom" action type
   - Understands intent even with imprecise selectors
   - Can combine multiple actions intelligently

## Configuration

### Environment Variables (.env)

```bash
# Google Generative AI (Required)
GOOGLE_API_KEY=your_google_api_key
GOOGLE_API_MODEL=gemini-2.0-flash-exp

# Daily LLM usage limit
DAILY_LLM_LIMIT=50
```

### LLM Configuration (app.py)

```python
llm = ChatGoogleGenerativeAI(
    model=os.getenv("GOOGLE_API_MODEL", "gemini-2.0-flash-exp"),
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.0,  # Deterministic for consistent automation
    max_tokens=300
)

# Compatibility wrapper for BrowserUse
llm = BrowserUseCompatibleLLM(base_llm)
```

## Execution Flow

### 1. User Builds Workflow
- Add steps via UI action selector
- Configure parameters (URLs, selectors, values)
- Preview natural language interpretation

### 2. Save & Execute
- Click "Run AI Agent" button
- Steps sent to `/api/browseruse/navigation` endpoint
- Backend validates and processes steps

### 3. AI Agent Execution
- Steps converted to natural language prompt
- BrowserUse Agent created with Google Gemini
- Playwright browser launches
- Agent executes tasks intelligently
- Results captured with screenshots

### 4. Results & Reporting
- Detailed execution report generated
- Success/failure status for each step
- Error messages with context
- Extracted content displayed
- Screenshot analysis (if enabled)

## Error Handling

### Comprehensive Reporting

```python
step_reports.append({
    "step": idx + 1,
    "description": description,
    "actual": actual_result,
    "status": "pass" | "fail",
    "error": error_message,
    "extracted_content": extracted_data,
    "screenshot_analysis": ai_visual_analysis,
    "raw": raw_result
})
```

### Error Categories

1. **Navigation Errors**: Timeout, DNS failure, SSL issues
2. **Element Errors**: Not found, not visible, not interactable
3. **Action Errors**: Click failed, fill blocked, assertion mismatch
4. **AI Agent Errors**: Token limit, API failure, timeout
5. **Screenshot Analysis**: Visual issues detected by AI

## Advanced Features

### Screenshot Analysis (Optional)

```python
def analyze_screenshot(screenshot_data):
    """Analyze screenshot for visual issues using AI"""
    # Checks for:
    # - UI rendering problems
    # - Error messages visible
    # - Missing content
    # - Unexpected popups
    # - Form validation errors
    # - Responsive design issues
```

### Custom AI Instructions

Use the "custom" action type for free-form AI automation:

```javascript
{
  action: 'custom',
  instruction: 'Find the product with the highest rating and add it to cart'
}
```

The AI agent will intelligently interpret and execute this complex task.

## Benefits Over Traditional Automation

| Traditional Automation | AI-Powered BrowserUse |
|------------------------|----------------------|
| Brittle selectors | Intelligent element detection |
| Fixed waits | Dynamic wait strategies |
| Exact steps required | High-level task description |
| Manual error handling | Automatic error recovery |
| No context awareness | Understands page semantics |
| Breaks with UI changes | Adapts to changes |

## Usage Examples

### Simple Login Flow
```javascript
[
  { action: 'navigate', url: 'https://example.com/login' },
  { action: 'fill', selector: '#username', value: 'testuser' },
  { action: 'fill', selector: '#password', value: 'testpass' },
  { action: 'click', selector: '#login-btn' },
  { action: 'assert_url', url: 'https://example.com/dashboard' }
]
```

### E-commerce Purchase Flow
```javascript
[
  { action: 'navigate', url: 'https://shop.example.com' },
  { action: 'fill', selector: '[aria-label="Search"]', value: 'laptop' },
  { action: 'press_key', key: 'Enter' },
  { action: 'wait_for_element', selector: '.product-card' },
  { action: 'custom', instruction: 'Click on the product with highest rating' },
  { action: 'click', selector: '#add-to-cart' },
  { action: 'assert_visible', selector: '.cart-confirmation' }
]
```

### Form Automation with Assertions
```javascript
[
  { action: 'navigate', url: 'https://forms.example.com' },
  { action: 'fill', selector: '#name', value: 'John Doe' },
  { action: 'fill', selector: '#email', value: 'john@example.com' },
  { action: 'select', selector: '#country', value: 'USA' },
  { action: 'check', selector: '#terms' },
  { action: 'click', selector: '#submit' },
  { action: 'assert_text', selector: '.success-message', text: 'Form submitted successfully' }
]
```

## Performance Considerations

- **Execution Time**: AI agent may take longer than traditional automation due to intelligent processing
- **Token Usage**: Each execution consumes API tokens based on prompt complexity
- **Rate Limiting**: Daily LLM usage limit enforced (configurable via `DAILY_LLM_LIMIT`)
- **Concurrency**: Supports multiple concurrent executions

## Troubleshooting

### Common Issues

1. **Agent Timeout**
   - Increase timeout in Agent configuration
   - Simplify complex prompts
   - Check network connectivity

2. **Element Not Found**
   - Verify selector accuracy
   - Add explicit wait steps
   - Use custom instruction for better AI interpretation

3. **API Rate Limits**
   - Check daily LLM usage quota
   - Reduce automation frequency
   - Increase `DAILY_LLM_LIMIT` if needed

4. **Unexpected Behavior**
   - Review natural language prompt generation
   - Add more specific selectors
   - Use assertions to verify expected state

## Future Enhancements

- [ ] Multi-browser support (Chrome, Firefox, Safari)
- [ ] Parallel step execution
- [ ] Visual regression testing
- [ ] Integration with CI/CD pipelines
- [ ] Custom AI model selection
- [ ] Enhanced screenshot analysis with object detection
- [ ] Workflow templates library
- [ ] Collaborative scenario sharing

## Related Documentation

- [BrowserUse Library](https://docs.browser-use.com/)
- [Playwright Documentation](https://playwright.dev/)
- [Google Generative AI](https://ai.google.dev/)
- [Co-Tester Setup Guide](../README.md)

## Support

For issues or questions:
- Check console logs for detailed error messages
- Review execution reports for step-by-step analysis
- Verify environment configuration
- Test with simpler scenarios first

---

**Remember**: The AI agent is intelligent but not perfect. Start with simple scenarios and gradually increase complexity. Always verify critical workflows with assertions!
