# VNC Architecture Diagram

## How It Works: Interactive Browser in Docker

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR COMPUTER                                │
│                                                                      │
│  ┌──────────────────┐         ┌──────────────────┐                 │
│  │   Your Browser   │         │   VNC Viewer     │                 │
│  │  localhost:5000  │         │  localhost:5900  │                 │
│  └────────┬─────────┘         └────────┬─────────┘                 │
│           │                             │                           │
│           │ HTTP requests               │ VNC protocol              │
│           │                             │ (screen + input)          │
└───────────┼─────────────────────────────┼───────────────────────────┘
            │                             │
            │                             │
┌───────────▼─────────────────────────────▼───────────────────────────┐
│                      DOCKER CONTAINER                                │
│                  (kishore1305/co-tester:vnc)                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Flask App (Port 5000)                        │ │
│  │  • Serves Co-Tester web interface                              │ │
│  │  • Handles Bug Builder requests                                │ │
│  │  • Launches Playwright when needed                             │ │
│  │  • YOUR SOURCE CODE (Protected! Hidden inside Docker!)         │ │
│  └───────────────────────────┬────────────────────────────────────┘ │
│                              │                                       │
│                              │ Launches browser                      │
│                              ▼                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                Virtual Display Layer (Xvfb :99)                 │ │
│  │                                                                 │ │
│  │  ┌──────────────────────────────────────────────────────────┐ │ │
│  │  │              Window Manager (Fluxbox)                     │ │ │
│  │  │                                                           │ │ │
│  │  │  ┌────────────────────────────────────────────────────┐ │ │ │
│  │  │  │         Chromium Browser Window                     │ │ │ │
│  │  │  │  • Runs on virtual display                          │ │ │ │
│  │  │  │  • Fully interactive (if headed mode)               │ │ │ │
│  │  │  │  • Receives mouse/keyboard from VNC                 │ │ │ │
│  │  │  │  • Playwright can record all interactions           │ │ │ │
│  │  │  └────────────────────────────────────────────────────┘ │ │ │
│  │  │                                                           │ │ │
│  │  └───────────────────────────────────────────────────────────┘ │ │
│  │                                                                 │ │
│  │  ┌───────────────────────────────────────────────────────────┐ │ │
│  │  │          x11vnc Server (Port 5900)                        │ │ │
│  │  │  • Captures display output                                │ │ │
│  │  │  • Streams to VNC Viewer on your computer                 │ │ │
│  │  │  • Sends mouse/keyboard input back to display             │ │ │
│  │  └───────────────────────────────────────────────────────────┘ │ │
│  │                                                                 │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Flow: Bug Builder Session

```
1. User opens Co-Tester in browser (localhost:5000)
   ┌─────────────┐
   │ Your Browser│──HTTP──▶ Flask App (in Docker)
   └─────────────┘

2. User clicks "Bug Builder" → "Start Recording"
   ┌─────────────┐
   │ Your Browser│──POST──▶ Flask App
   └─────────────┘           │
                             │ Flask calls Playwright
                             ▼
                   ┌──────────────────────┐
                   │ Playwright launches  │
                   │ Chromium on :99      │
                   └──────────────────────┘
                             │
                             ▼
                   ┌──────────────────────┐
                   │ Browser window opens │
                   │ on virtual display   │
                   └──────────────────────┘

3. VNC streams the browser window to your computer
   ┌─────────────┐           ┌──────────────┐
   │ VNC Viewer  │◀──VNC────│ x11vnc Server│
   │ (Your PC)   │   Stream  │ (In Docker)  │
   └─────────────┘           └──────────────┘
        │                           │
        │ Shows browser window      │ Captures display :99
        ▼                           │
   ┌─────────────┐                  │
   │  You see:   │                  │
   │  ┌────────┐ │                  │
   │  │Browser │ │                  │
   │  │Window  │ │◀─────────────────┘
   │  └────────┘ │
   └─────────────┘

4. You interact with browser in VNC window
   ┌─────────────┐
   │ You click & │──VNC────▶ x11vnc ──▶ Xvfb :99 ──▶ Browser
   │ type in VNC │ Protocol              Virtual      (receives
   └─────────────┘                       Display      input!)

5. Playwright records your actions
   ┌─────────────┐
   │  Browser    │──Events──▶ Playwright Codegen
   │ (in Docker) │            │
   └─────────────┘            │ Records:
                              │ • page.goto(...)
                              │ • page.click(...)
                              │ • page.fill(...)
                              ▼
                   ┌──────────────────────┐
                   │ Test script saved in │
                   │ codegen-output/      │
                   └──────────────────────┘

6. Results sent back to your browser
   ┌─────────────┐
   │ Your Browser│◀──HTTP─── Flask App
   │             │  (test     (retrieves
   │ Shows test  │   script)   recorded
   │ script!     │             steps)
   └─────────────┘
```

---

## Comparison: With vs Without VNC

### ❌ Without VNC (Your Original Problem)

```
Docker Container:
┌──────────────────────────────┐
│ Xvfb :99                     │
│  └─ Browser (invisible!)     │
│                              │
│ You run: PLAYWRIGHT_HEADLESS=false
│ Browser opens, but WHERE?    │
│ Answer: Inside Docker on :99 │
│ Problem: You can't see it!   │
│                              │
│ Bug Builder needs clicks     │
│ But you can't click what     │
│ you can't see! ❌            │
└──────────────────────────────┘

Your Computer:
┌──────────────────────────────┐
│ Nothing to see here!         │
│ Browser is trapped in Docker │
└──────────────────────────────┘
```

### ✅ With VNC (New Solution)

```
Docker Container:
┌──────────────────────────────┐
│ Xvfb :99                     │
│  └─ Browser (runs here)      │
│      │                       │
│      └─ x11vnc (port 5900)   │
│          │                   │
│          └─ Streams display  │
└──────────┼───────────────────┘
           │ VNC Protocol
           ▼
Your Computer:
┌──────────────────────────────┐
│ VNC Viewer (localhost:5900)  │
│  ┌────────────────────────┐  │
│  │  You see browser here! │  │
│  │  ┌──────────────────┐  │  │
│  │  │ [Browser Window] │  │  │
│  │  │  Interactive!    │  │  │
│  │  │  Clickable!      │  │  │
│  │  └──────────────────┘  │  │
│  └────────────────────────┘  │
│                              │
│ Click & type here ──▶        │
│ Browser receives it! ✅      │
└──────────────────────────────┘
```

---

## Security & Protection

### 🔒 What Users CAN'T Access:

```
Docker Container (Opaque Black Box):
┌────────────────────────────────────┐
│ 🔒 app.py (your source code)       │
│ 🔒 routes/*.py                      │
│ 🔒 models/*.py                      │
│ 🔒 utils/*.py                       │
│ 🔒 All business logic                │
│ 🔒 Implementation details            │
│                                    │
│ Users CANNOT:                      │
│  ❌ docker exec into container     │
│  ❌ View source files               │
│  ❌ Extract Python code             │
│  ❌ Reverse engineer easily         │
└────────────────────────────────────┘
```

### 👁️ What Users CAN Access (via VNC):

```
VNC Window Shows:
┌────────────────────────────────────┐
│ ✅ Browser window                   │
│ ✅ Mouse cursor                     │
│ ✅ Web pages being tested           │
│ ✅ Playwright automation in action  │
│                                    │
│ But NOT:                           │
│  ❌ Python source code              │
│  ❌ File system                     │
│  ❌ Terminal access                 │
│  ❌ Docker internals                │
└────────────────────────────────────┘
```

---

## Performance Flow

```
Standard Image (Headless):
App ──▶ Playwright ──▶ Browser (headless) ──▶ Results
                      ▲                    ▼
                      │                 Screenshots
                    Fast!               Fast!
                    ~300MB RAM          Low CPU

VNC Image (VNC Disabled):
App ──▶ Playwright ──▶ Browser (headless) ──▶ Results
                      ▲                    ▼
                      │                 Screenshots
                    Fast!               Fast!
                    ~300MB RAM          Low CPU
                    (Same as standard!)

VNC Image (VNC Enabled):
App ──▶ Playwright ──▶ Browser (headed) ──▶ Results
                      ▲                  │
                      │                  ├──▶ Screenshots
                      │                  │
                      │                  └──▶ VNC Stream
                      │                        │
                      │                        ▼
                      │                  x11vnc (encoding)
                      │                        │
                      │                        ▼
                      │                  Your VNC Viewer
                    Slower              ~400MB RAM
                    (visible!)          Medium CPU
                                       (VNC encoding)
```

---

## Summary Diagram

```
                     Co-Tester Deployment Models

┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│  Standard Image     │  │  VNC Image          │  │  Local Development  │
├─────────────────────┤  ├─────────────────────┤  ├─────────────────────┤
│ Automated features  │  │ Interactive         │  │ Full development    │
│ Headless browser    │  │ features            │  │ Visible browser     │
│ No VNC              │  │ Bug Builder works   │  │ Direct interaction  │
│ Fast & efficient    │  │ VNC shows browser   │  │ Source code exposed │
│ Source protected ✅ │  │ Source protected ✅ │  │ No protection ❌    │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
         │                        │                         │
         │                        │                         │
         ▼                        ▼                         ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ docker run          │  │ docker run          │  │ python app.py       │
│ -p 5000:5000        │  │ -p 5000:5000        │  │                     │
│ kishore1305/        │  │ -p 5900:5900        │  │ Browser on your     │
│ co-tester:latest    │  │ -e ENABLE_VNC=true  │  │ display             │
│                     │  │ kishore1305/        │  │                     │
│ Use for:            │  │ co-tester:vnc       │  │ Use for:            │
│ • API testing       │  │                     │  │ • Development       │
│ • Reports           │  │ Use for:            │  │ • Debugging         │
│ • Automation        │  │ • Bug Builder       │  │ • Team coding       │
│                     │  │ • Test Generator    │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

---

## The "Aha!" Moment

```
Before Understanding VNC:
"I set PLAYWRIGHT_HEADLESS=false but nothing happens! 
 Where is the browser?!"
 
         ╔═══════════════════════════╗
         ║  Browser is in Docker!    ║
         ║  You just can't see it    ║
         ╚═══════════════════════════╝

After Understanding VNC:
"Oh! The browser IS running, I just need VNC Viewer 
 to see inside Docker and interact with it!"
 
         ╔═══════════════════════════╗
         ║  VNC = Window into Docker ║
         ║  Shows browser + captures ║
         ║  your clicks/typing       ║
         ╚═══════════════════════════╝
```

---

**Bottom Line**: 
VNC lets you "remote desktop" into the Docker container to see and control the browser, while keeping your source code safely hidden inside Docker! 🎯
