# Co-Tester Dependencies Reference

## Overview

This document provides a comprehensive reference of all dependencies used in the Co-Tester project, organized by category.

---

## Python Dependencies (requirements.txt)

### Flask Framework (9 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| Flask | 3.1.0 | Core web framework |
| Flask-SQLAlchemy | 3.1.1 | Database ORM integration |
| Flask-Login | 0.6.3 | User authentication |
| Flask-Mail | 0.10.0 | Email support |
| Flask-Migrate | 4.1.0 | Database migrations |
| Flask-Session | 0.8.0 | Server-side sessions |
| Flask-Caching | 2.3.1 | Response caching |
| flask-cors | 5.0.1 | Cross-origin support |
| Werkzeug | 3.1.3 | WSGI utility library |

### Database (3 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| SQLAlchemy | 2.0.40 | SQL toolkit and ORM |
| alembic | 1.15.2 | Database migration tool |
| greenlet | 3.1.1 | Lightweight concurrency |

### AI/ML Libraries (18 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| google-generativeai | 0.5.4 | **Gemini AI - Core MBT feature** |
| google-ai-generativelanguage | 0.6.4 | Gemini language support |
| google-api-core | 2.24.0 | Google API client core |
| google-auth | 2.37.0 | Google authentication |
| googleapis-common-protos | 1.66.0 | Common protocol buffers |
| protobuf | 5.29.3 | Protocol buffers |
| proto-plus | 1.25.0 | Proto wrapper library |
| openai | 1.59.7 | OpenAI API client |
| langchain | 0.3.14 | **LLM orchestration** |
| langchain-core | 0.3.28 | LangChain core library |
| langchain-openai | 0.2.15 | OpenAI LangChain integration |
| langchain-google-genai | 2.0.8 | Gemini LangChain integration |
| langchain-community | 0.3.14 | Community integrations |
| langchain-text-splitters | 0.3.4 | Text splitting utilities |
| langsmith | 0.2.11 | LangChain monitoring |
| orjson | 3.10.14 | Fast JSON library |

### Browser Automation (2 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| playwright | ≥1.40.0 | **Browser automation - MBT execution** |
| selenium | 4.27.1 | Alternative browser automation |

**Note**: `browser-use` package (AI-powered automation) must be installed separately:
```bash
pip install git+https://github.com/browser-use/browser-use.git
```

### Authentication & Security (5 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| Authlib | 1.6.5 | OAuth/OpenID library |
| cryptography | 44.0.3 | Cryptographic recipes |
| cffi | 1.17.1 | C Foreign Function Interface |
| pycparser | 2.22 | C parser |
| PyJWT | 2.10.1 | JSON Web Token |

### HTTP & API (10 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| requests | 2.32.3 | HTTP library |
| httpx | 0.28.1 | Async HTTP client |
| urllib3 | 2.3.0 | HTTP client library |
| certifi | 2024.12.14 | SSL certificates |
| httpcore | 1.0.7 | HTTP core functionality |
| h11 | 0.14.0 | HTTP/1.1 protocol |
| anyio | 4.8.0 | Async I/O library |
| idna | 3.10 | Internationalized domains |
| charset-normalizer | 3.4.0 | Character encoding |
| sniffio | 1.3.1 | Async library detection |

### Document Processing (4 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| PyPDF2 | 3.0.1 | PDF manipulation |
| pypdf | 5.1.0 | PDF utilities |
| python-docx | 1.1.2 | Word document processing |
| lxml | 5.3.0 | XML/HTML parsing |

### Image Processing & OCR (4 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| pytesseract | 0.3.13 | OCR wrapper for Tesseract |
| Pillow | 11.0.0 | Image processing |
| pdf2image | 1.17.0 | PDF to image conversion |
| opencv-python | 4.10.0.84 | Computer vision |

### Data Processing (2 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| pandas | 2.2.3 | Data analysis |
| numpy | 2.2.1 | Numerical computing |

### Visualization & Reporting (9 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| reportlab | 4.2.5 | PDF generation |
| matplotlib | 3.10.0 | Plotting library |
| seaborn | 0.13.2 | Statistical visualization |
| contourpy | 1.3.1 | Contour calculations |
| cycler | 0.12.1 | Composable style cycles |
| fonttools | 4.55.3 | Font manipulation |
| kiwisolver | 1.4.7 | Constraint solver |
| packaging | 24.2 | Package version handling |
| pyparsing | 3.2.0 | Parsing library |

### Task Scheduling (3 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| APScheduler | 3.11.0 | **Background task scheduling** |
| pytz | 2024.2 | Timezone definitions |
| tzlocal | 5.2 | Local timezone detection |

### Utilities (17 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| python-dotenv | 1.1.0 | Environment variables |
| pydantic | 2.10.5 | Data validation |
| pydantic-core | 2.27.2 | Pydantic core |
| annotated-types | 0.7.0 | Type annotations |
| typing_extensions | 4.12.2 | Typing backports |
| python-dateutil | 2.9.0.post0 | Date utilities |
| six | 1.17.0 | Python 2/3 compatibility |
| attrs | 24.3.0 | Class decorators |
| tqdm | 4.67.1 | Progress bars |
| tenacity | 9.0.0 | Retry library |
| jsonpatch | 1.33 | JSON patching |
| jsonpointer | 3.0.0 | JSON pointer syntax |
| distro | 1.9.0 | Linux distribution detection |
| regex | 2024.11.6 | Advanced regex |
| rich | 13.9.4 | Terminal formatting |
| markdown-it-py | 3.0.0 | Markdown parser |
| Pygments | 2.18.0 | Syntax highlighting |

### Database Migration (1 package)
| Package | Version | Purpose |
|---------|---------|---------|
| Mako | 1.3.10 | Template library for Alembic |

### Production Server (1 package)
| Package | Version | Purpose |
|---------|---------|---------|
| gunicorn | 23.0.0 | WSGI HTTP server |

### Optional Development Packages
```python
# Testing
pytest==7.4.3
pytest-cov==4.1.0
pytest-playwright==0.4.3
pytest-asyncio==0.21.1

# Code Quality
black==23.12.1
flake8==6.1.0
mypy==1.7.1
pylint==3.0.3
```

**Total Python Packages**: ~90 packages

---

## Node.js Dependencies (package.json)

### Core Dependencies (7 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| xstate | ^5.21.0 | **State machine library - Core MBT** |
| @xstate/test | ^1.0.0 | **Test generation from state machines** |
| @xstate/graph | ^2.0.0 | **Graph algorithms for state traversal** |
| playwright | ^1.43.1 | Browser automation |
| @playwright/test | ^1.43.1 | Playwright test runner |
| express | ^5.1.0 | Web server |
| cors | ^2.8.5 | CORS middleware |

### Development Dependencies (2 packages)
| Package | Version | Purpose |
|---------|---------|---------|
| @types/node | ^20.0.0 | TypeScript types for Node.js |
| typescript | ^5.0.0 | TypeScript compiler |

**Total Node Packages**: 9 packages

---

## Feature Dependency Matrix

### Model-Based Testing (MBT) Feature

#### Backend (Python):
- ✅ Flask 3.1.0 - Web framework
- ✅ SQLAlchemy 2.0.40 - Database ORM
- ✅ google-generativeai 0.5.4 - AI state discovery
- ✅ playwright ≥1.40.0 - Test execution
- ✅ APScheduler 3.11.0 - Background tasks

#### Frontend (Node.js):
- ✅ xstate 5.21.0 - State machine modeling
- ✅ @xstate/test 1.0.0 - Test generation
- ✅ @xstate/graph 2.0.0 - Path algorithms
- ✅ @playwright/test 1.43.1 - Test runner

### AI-Powered Testing
- ✅ google-generativeai 0.5.4 - Gemini AI
- ✅ openai 1.59.7 - OpenAI GPT
- ✅ langchain 0.3.14 - LLM orchestration
- ✅ langchain-google-genai 2.0.8 - Gemini integration
- ✅ langchain-openai 0.2.15 - OpenAI integration

### Browser Automation
- ✅ playwright ≥1.40.0 - Cross-browser testing
- ✅ selenium 4.27.1 - WebDriver protocol
- ✅ browser-use (external) - AI-powered automation

### Auto-Healing & Bug Builder
- ✅ playwright ≥1.40.0 - Element detection
- ✅ google-generativeai 0.5.4 - Smart healing

### API Testing
- ✅ requests 2.32.3 - HTTP client
- ✅ httpx 0.28.1 - Async HTTP
- ✅ Flask-CORS 5.0.1 - CORS support

### Document Processing
- ✅ PyPDF2 3.0.1 - PDF manipulation
- ✅ python-docx 1.1.2 - Word documents
- ✅ pytesseract 0.3.13 - OCR
- ✅ Pillow 11.0.0 - Image processing

### Reporting & Visualization
- ✅ reportlab 4.2.5 - PDF reports
- ✅ matplotlib 3.10.0 - Charts
- ✅ seaborn 0.13.2 - Statistical plots

---

## System Dependencies

### Required System Packages

#### Windows:
```powershell
# Tesseract OCR (for OCR features)
choco install tesseract

# Or download from:
# https://github.com/UB-Mannheim/tesseract/wiki
```

#### macOS:
```bash
# Tesseract OCR
brew install tesseract

# Node.js 20.x
brew install node@20
```

#### Linux (Ubuntu/Debian):
```bash
# Tesseract OCR
sudo apt-get install tesseract-ocr

# Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# System libraries
sudo apt-get install -y \
    python3-dev \
    build-essential \
    libssl-dev \
    libffi-dev
```

---

## Installation Commands

### Complete Setup (All Dependencies)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install browser-use
pip install git+https://github.com/browser-use/browser-use.git

# 3. Install Node.js dependencies
npm install

# 4. Install Playwright browsers
playwright install

# 5. Verify installation
python -c "import flask, playwright, google.generativeai; print('Python OK')"
npm list xstate @xstate/test
```

### Quick Start (Minimal)

```bash
# Just Python dependencies
pip install -r requirements.txt

# Just Node dependencies
npm install
```

---

## API Keys Required

### Essential:
- `GEMINI_API_KEY` - Google Gemini AI (for MBT state discovery)

### Optional:
- `OPENAI_API_KEY` - OpenAI GPT (alternative AI backend)
- `AZURE_OPENAI_KEY` - Azure OpenAI (enterprise option)
- `JIRA_API_TOKEN` - Jira integration
- `GOOGLE_CLIENT_ID` - OAuth authentication

---

## Dependency Updates

### Check for Updates:

```bash
# Python
pip list --outdated

# Node.js
npm outdated
```

### Update Dependencies:

```bash
# Python (specific package)
pip install --upgrade <package-name>

# Node.js (specific package)
npm update <package-name>

# Update all (use with caution)
pip install --upgrade -r requirements.txt
npm update
```

---

## Troubleshooting

### Common Dependency Issues:

1. **Playwright browsers missing**:
   ```bash
   playwright install
   ```

2. **XState not found**:
   ```bash
   npm install xstate @xstate/test @xstate/graph
   ```

3. **Gemini API errors**:
   - Verify `GEMINI_API_KEY` in `.env`
   - Check quota: https://console.cloud.google.com/

4. **Import errors**:
   ```bash
   pip install --force-reinstall -r requirements.txt
   ```

---

## License Information

All dependencies are used under their respective open-source licenses:
- Flask: BSD-3-Clause
- Playwright: Apache-2.0
- XState: MIT
- SQLAlchemy: MIT
- Google AI: Apache-2.0

---

**Last Updated**: 2025-01-07  
**Document Version**: 1.0  
**Maintained by**: Co-Tester Team
