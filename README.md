# Co-Tester - Comprehensive Testing Automation Platform

![Co-Tester](static/images/logo.png)

## 🎯 Overview

Co-Tester is a comprehensive testing automation platform that combines AI-powered test generation, browser automation, API testing, and Jira integration into a single powerful tool.

### ✨ Key Features

- **🤖 AI-Powered Test Generation** - Generate manual test cases using Google Gemini AI
- **🎭 Auto-Healing UI Recorder** - Record and replay browser interactions with self-healing capabilities
- **🔌 API Testing Studio** - Test REST and GraphQL APIs with intelligent test generation
- **📋 Jira Integration** - Seamless authentication and project management
- **📚 Context Builder** - Create comprehensive test documentation with AI assistance
- **🎯 Bulk Test Generation** - Generate multiple test scenarios efficiently
- **📊 Reporting & Analytics** - Detailed test execution reports

## 🚀 Quick Start

### Prerequisites
- Python 3.8+ (recommended: 3.9+)
- Node.js 20.x
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd Co-Tester
   ```

2. **Run the setup script**
   ```bash
   # Windows
   setup.bat
   
   # Linux/Mac
   ./setup.sh
   ```

3. **Configure environment**
   - Copy `.env.example` to `.env`
   - Fill in your configuration values (see Configuration section)

4. **Start the application**
   ```bash
   python app.py
   ```

5. **Access the application**
   - Open http://localhost:5000 in your browser
   - Login with Jira OAuth or use guest mode

## ⚙️ Configuration

Create a `.env` file with the following configuration:

```env
# Required - Flask Configuration
SECRET_KEY=your-super-secret-key-here
FLASK_ENV=development

# Required - Google AI for test generation
GOOGLE_API_KEY=your-google-gemini-api-key
GOOGLE_API_MODEL=gemini-2.0-flash-exp

# Optional - Jira OAuth (for full Jira integration)
JIRA_CLIENT_ID=your-jira-oauth-client-id
JIRA_CLIENT_SECRET=your-jira-oauth-client-secret
JIRA_CALLBACK_URL=http://localhost:5000/api/jira/oauth/callback

# Optional - Production configuration
JIRA_CLIENT_ID_PROD=your-production-jira-client-id
JIRA_CLIENT_SECRET_PROD=your-production-jira-client-secret
JIRA_CALLBACK_URL_PROD=https://yourdomain.com/api/jira/oauth/callback

# Optional - Rate limiting and admin access
DAILY_LLM_LIMIT=20
ADMIN_EMAILS=admin@yourcompany.com,manager@yourcompany.com
```

### 🔑 Getting API Keys

#### Google AI API Key
1. Visit [Google AI Studio](https://ai.google.dev/)
2. Create a new project or select existing
3. Enable the Generative AI API
4. Create an API key
5. Add it to your `.env` file as `GOOGLE_API_KEY`

#### Jira OAuth Setup (Optional)
1. Go to [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/)
2. Create a new OAuth 2.0 (3LO) app
3. Add callback URL: `http://localhost:5000/api/jira/oauth/callback`
4. Configure scopes: `read:jira-user`, `read:jira-work`
5. Add credentials to your `.env` file

## 📖 User Guide

### 🏠 Home Dashboard
- Quick access to all features
- Authentication status and user info
- Recent activity overview

### 🤖 API Co-Test
- **REST API Testing**: Test HTTP endpoints with AI-generated scenarios
- **GraphQL Testing**: Query and mutation testing with schema validation
- **Test Generation**: AI-powered test case creation
- **Environment Management**: Multiple environment support

### 🎭 Auto-Healing Recorder
- **Record Interactions**: Capture user interactions in real-time
- **Self-Healing**: Automatically adapt to UI changes
- **Code Generation**: Export tests as Playwright, Selenium, or Cypress code
- **Visual Validation**: Screenshot comparison and validation

### 📝 Manual Test Generator
- **AI-Powered Generation**: Create comprehensive test cases using AI
- **Bulk Generation**: Generate multiple test scenarios at once
- **Export Options**: Download as PDF, Word, Excel, or ZIP
- **Custom Templates**: Use predefined or custom test templates

### 📚 Context Builder
- **Documentation Assistant**: AI-powered test documentation creation
- **Knowledge Base**: Build and maintain testing knowledge
- **Collaboration**: Share contexts across team members

## 🛠️ Development

### Project Structure
```
Co-Tester/
├── app.py                 # Main Flask application
├── models/               # Database models
├── routes/               # API routes
├── static/               # CSS, JS, images
├── templates/            # HTML templates
├── utils/                # Utility functions
├── migrations/           # Database migrations
└── tests/                # Test files
```

### Running in Development Mode
```bash
# Activate virtual environment
co-tester-env\Scripts\activate  # Windows
source co-tester-env/bin/activate  # Linux/Mac

# Install development dependencies
pip install -r requirements-dev.txt

# Run with debug mode
export FLASK_ENV=development  # Linux/Mac
set FLASK_ENV=development     # Windows
python app.py
```

### Running Tests
```bash
# Run unit tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

## 🚀 Deployment

### Production with Gunicorn
```bash
# Install production dependencies
pip install gunicorn

# Run with Gunicorn
gunicorn --bind 0.0.0.0:8000 --workers 4 app:app
```

### Docker Deployment
```bash
# Build image
docker build -t co-tester .

# Run container
docker run -p 8000:8000 --env-file .env co-tester
```

### Heroku Deployment
The application is configured for Heroku deployment with:
- `Procfile` for process configuration
- `package.json` for Node.js buildpack
- `requirements.txt` for Python dependencies

## 🔧 Troubleshooting

### Common Issues

**1. Playwright Installation Issues**
```bash
npx playwright install
npx playwright install-deps  # Linux only
```

**2. Database Issues**
```bash
# Reset database
rm instance/db.sqlite3
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

**3. Port Already in Use**
```bash
# Change port in app.py or set environment variable
export PORT=8080  # Linux/Mac
set PORT=8080     # Windows
```

**4. Import Errors**
```bash
# Ensure virtual environment is activated
# Reinstall dependencies
pip install -r requirements.txt
```

## 📊 Features Overview

| Feature | Description | Status |
|---------|-------------|--------|
| API Testing | REST & GraphQL API testing | ✅ Ready |
| UI Automation | Browser automation with Playwright | ✅ Ready |
| AI Test Generation | Gemini AI-powered test creation | ✅ Ready |
| Jira Integration | OAuth authentication & project sync | ✅ Ready |
| Context Builder | AI documentation assistant | ✅ Ready |
| Bulk Generation | Multiple test scenario creation | ✅ Ready |
| Auto-healing | Self-repairing UI tests | ✅ Ready |
| Reporting | Comprehensive test reports | ✅ Ready |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: [Wiki](https://github.com/your-repo/Co-Tester/wiki)
- **Issues**: [GitHub Issues](https://github.com/your-repo/Co-Tester/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-repo/Co-Tester/discussions)

## 🎉 Acknowledgments

- **Google Gemini AI** for intelligent test generation
- **Playwright** for robust browser automation
- **Flask** for the web framework
- **Jira** for project management integration

---

**Made with ❤️ by the Co-Tester Team**