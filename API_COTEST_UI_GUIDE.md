# API Co-Test V2 - UI Guide

## 🎨 What You Should See

### Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ 🚀 API Co-Test Header                                          │
├─────────────────────────────────────────────────────────────────┤
│ [💼 My Workspace ▼]  [🌍 Development ▼]     [⚙️ Variables]    │ ← Toolbar
├──────────────┬──────────────────────────────────────────────────┤
│              │                                                  │
│  📜 History  │  REST API | GraphQL | cURL Runner | Collections │ ← Tabs
│  ⭐ Favorites│                                                  │
│              │  ┌────────────────────────────────────────────┐ │
│  [Request 1] │  │ Method: [GET ▼]                            │ │
│  GET /users  │  │ URL: https://api.example.com/users         │ │
│  200 - 45ms  │  │                                            │ │
│              │  │ Params | Auth | Headers | Body             │ │
│  [Request 2] │  │                                            │ │
│  POST /login │  │ [Send Request]                             │ │
│  201 - 120ms │  └────────────────────────────────────────────┘ │
│              │                                                  │
│              │  Response:                                       │
│              │  ┌────────────────────────────────────────────┐ │
│              │  │ Status: 200 OK | Time: 45ms                │ │
│              │  │ Body | Headers | Cookies                   │ │
│              │  │                                            │ │
│              │  │ { "users": [...] }                         │ │
│              │  └────────────────────────────────────────────┘ │
└──────────────┴──────────────────────────────────────────────────┘
```

---

## 🎯 Features Overview

### 1. Toolbar (Top Bar)
**Location:** Sticky at the top of the page

**Components:**
- **Workspace Selector** - Switch between different workspaces
  - Click to see dropdown
  - Shows current workspace name
  - Option to create new workspace
  
- **Environment Selector** - Switch between environments
  - Click to see dropdown
  - Shows active environment (green checkmark)
  - Quick switch between Dev/Staging/Prod
  - Option to create new environment
  
- **Variables Button** - Manage environment variables
  - Opens modal with variable editor
  - Add/edit/delete variables
  - Mark variables as secret (masked)

---

### 2. Sidebar (Left Panel)
**Location:** Left side, 300px wide

**Tabs:**

#### 📜 History Tab (Default)
Shows all executed requests with:
- HTTP Method (GET, POST, PUT, DELETE) with color coding
- Request URL (truncated if long)
- Response Status Code (200, 404, 500, etc.)
- Response Time in milliseconds
- Execution timestamp (relative time)

**Actions:**
- Click any history item to load it into the request builder
- Automatically saves every request you execute

#### ⭐ Favorites Tab
Shows starred/favorite requests with:
- HTTP Method
- Request name or URL
- Star icon (click to remove from favorites)

**Actions:**
- Click any favorite to load it
- Star icon in request builder to add current request

---

### 3. Main Content Area (Center/Right)
**Location:** Takes up remaining space

**Original Tabs (Still Working!):**

#### 🌐 REST API Tab
- Full request builder
- Method selector (GET, POST, PUT, DELETE, PATCH)
- URL input with variable substitution
- Sub-tabs:
  - **Params** - Query parameters (key-value pairs)
  - **Auth** - Authentication (Bearer, Basic, etc.)
  - **Headers** - HTTP headers
  - **Body** - Request body (JSON, form-data, raw)
- Send button
- Response viewer with syntax highlighting

#### 🔷 GraphQL Tab
- GraphQL query editor
- Variables editor
- Schema explorer (if available)
- Send button
- Response viewer

#### 💻 cURL Runner Tab
- Paste cURL commands
- Auto-parse and execute
- Convert to REST request
- Example commands available

#### 📁 Collections Tab
- Import Postman collections
- Organize requests in folders
- Run entire collections
- Export collections

---

## 🎨 Visual Elements

### Color Coding

**HTTP Methods:**
- `GET` - Blue background (#dbeafe)
- `POST` - Green background (#dcfce7)
- `PUT` - Yellow background (#fef3c7)
- `DELETE` - Red background (#fee2e2)
- `PATCH` - Purple background (#f3e8ff)

**Status Codes:**
- `2xx` - Green text (Success)
- `3xx` - Blue text (Redirect)
- `4xx` - Orange text (Client Error)
- `5xx` - Red text (Server Error)

**UI Theme:**
- Primary: Indigo (#6366f1)
- Success: Green (#10b981)
- Error: Red (#ef4444)
- Warning: Orange (#f59e0b)
- Info: Blue (#3b82f6)

---

## 🎮 Interactions

### Workspace Management

**Create Workspace:**
1. Click workspace dropdown
2. Click "Create Workspace"
3. Enter name and description
4. Click "Create"
5. New workspace becomes active

**Switch Workspace:**
1. Click workspace dropdown
2. Click desired workspace
3. Environments and variables load automatically

**Delete Workspace:**
1. Click workspace dropdown
2. Hover over workspace
3. Click trash icon
4. Confirm deletion

### Environment Management

**Create Environment:**
1. Click environment dropdown
2. Click "Create Environment"
3. Enter name (e.g., "Staging")
4. Click "Create"

**Switch Environment:**
1. Click environment dropdown
2. Click desired environment
3. Green checkmark shows active environment
4. Variables update automatically

**Manage Variables:**
1. Click "Variables" button in toolbar
2. Modal opens with variable editor
3. Add rows with key/value pairs
4. Check "Secret" to mask sensitive values
5. Click "Save All"

### Request History

**View History:**
- History tab shows last 50 requests
- Newest at top
- Scroll to see more

**Load from History:**
1. Click any history item
2. Request loads into active tab
3. All details preserved (method, URL, headers, body)

**Clear History:**
- API endpoint available: `DELETE /api/v1/workspaces/{id}/history/clear`
- (UI button coming in next phase)

### Favorites

**Add to Favorites:**
1. Build your request
2. Click star icon (coming in next phase)
3. Request saved to favorites

**Load from Favorites:**
1. Switch to Favorites tab
2. Click any favorite
3. Request loads into active tab

**Remove from Favorites:**
1. Hover over favorite item
2. Click star icon
3. Removed from list

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + E` | Toggle environment dropdown |
| `Ctrl/Cmd + Enter` | Send request (coming soon) |
| `Ctrl/Cmd + K` | Quick search (coming soon) |
| `Ctrl/Cmd + S` | Save request (coming soon) |

---

## 🔧 Variable Substitution

### Syntax
Use double curly braces: `{{variableName}}`

### Examples

**In URL:**
```
https://{{baseUrl}}/api/{{version}}/users
```

**In Headers:**
```
Authorization: Bearer {{authToken}}
```

**In Body:**
```json
{
  "userId": "{{userId}}",
  "apiKey": "{{apiKey}}"
}
```

### Variable Precedence
1. **Environment Variables** (highest priority)
2. **Global Variables**
3. **Dynamic Variables** (coming soon)
   - `{{$timestamp}}` - Current Unix timestamp
   - `{{$uuid}}` - Random UUID
   - `{{$randomInt}}` - Random integer

---

## 📱 Responsive Design

### Desktop (> 768px)
- Sidebar visible (300px)
- Full toolbar
- All features accessible

### Mobile (< 768px)
- Sidebar hidden by default
- Hamburger menu to toggle sidebar
- Toolbar stacks vertically
- Touch-friendly buttons

---

## 🎨 Customization

### Theme (Coming Soon)
- Light mode (default)
- Dark mode toggle
- Custom color schemes

### Layout (Coming Soon)
- Resizable sidebar
- Collapsible panels
- Custom tab order

---

## 🐛 Troubleshooting

### "Failed to load workspaces"
**Solution:** 
- Check browser console for errors
- Verify API endpoints are accessible
- Try refreshing the page

### Variables not substituting
**Solution:**
- Check variable name matches exactly (case-sensitive)
- Verify environment is active
- Check variable has a value

### History not showing
**Solution:**
- Execute a request first
- Check workspace is selected
- Verify database connection

### Tabs not switching
**Solution:**
- Check browser console for JavaScript errors
- Clear browser cache
- Refresh page

---

## 📊 Current Limitations

### Phase 1 (Current)
- ✅ Workspace/environment management
- ✅ Variable management
- ✅ History tracking
- ✅ Favorites system
- ❌ Variable substitution in requests (Phase 2)
- ❌ Request execution with environment (Phase 2)
- ❌ Collections management (Phase 3)
- ❌ Test scripts (Phase 4)

### Coming in Phase 2
- Variable substitution in URLs, headers, body
- Enhanced request execution
- Better response viewer
- Request chaining
- Dynamic variables

---

## 💡 Tips & Best Practices

### Organizing Workspaces
- Create separate workspaces for different projects
- Use descriptive names (e.g., "E-commerce API", "Auth Service")
- Keep team workspaces separate from personal

### Managing Environments
- Standard setup: Development, Staging, Production
- Use consistent variable names across environments
- Mark sensitive values as "Secret"

### Using Variables
- Store base URLs as variables
- Keep auth tokens in variables
- Use descriptive variable names (camelCase or snake_case)
- Document variables in descriptions

### Request History
- Review history before re-running requests
- Use history to debug issues
- Star frequently used requests

---

## 🎓 Quick Start Guide

### First Time Setup (5 minutes)

1. **Navigate to API Co-Test**
   - Go to `/api-co-test`

2. **Create Your First Workspace**
   - Click workspace dropdown
   - Click "Create Workspace"
   - Name it "My API Tests"
   - Click "Create"

3. **Set Up Environments**
   - Click environment dropdown
   - Default "Development" environment exists
   - Click "Create Environment" to add "Staging"
   - Click "Create Environment" to add "Production"

4. **Add Variables**
   - Click "Variables" button
   - Add variable: `baseUrl` = `https://api.example.com`
   - Add variable: `authToken` = `your-token-here` (mark as Secret)
   - Click "Save All"

5. **Make Your First Request**
   - Go to REST API tab
   - Method: GET
   - URL: `{{baseUrl}}/users`
   - Click "Send"
   - Check History tab to see the request

6. **Star Your Favorite**
   - After successful request
   - Click star icon (coming soon)
   - Check Favorites tab

---

## 📞 Support

### Getting Help
- Check this guide first
- Review browser console for errors
- Check API_COTEST_PROGRESS.md for known issues
- Report bugs with screenshots

### Feature Requests
- See API_CO_TEST_ENHANCEMENT_PLAN.md for roadmap
- Suggest improvements
- Vote on upcoming features

---

**Last Updated:** October 21, 2025
**Version:** 2.0 (Phase 1 Complete)
**Status:** ✅ Fully Functional
