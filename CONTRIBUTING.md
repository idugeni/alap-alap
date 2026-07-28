# Contributing to Alap-Alap

Thank you for your interest in contributing to Alap-Alap! This document provides guidelines and information for contributors.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Issue Guidelines](#issue-guidelines)

## Code of Conduct

Please be respectful and professional in all interactions. We are building a community around open-source captcha solving tools.

## Getting Started

1. Fork the repository
2. Clone your fork
3. Create a feature branch
4. Make your changes
5. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.8+
- Git
- Camoufox

### Installation

```bash
# Clone the repository
git clone https://github.com/idugeni/alap-alap.git
cd alap-alap

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Install Camoufox browser
camoufox fetch
```

### Project Structure

```
alap-alap/
├── src/
│   └── alap_alap/
│       ├── __init__.py
│       ├── core/
│       │   └── main.py
│       ├── detector/
│       │   └── sitekey_detector.py
│       ├── solver/
│       │   └── captcha_solver.py
│       ├── browser/
│       │   └── camoufox_manager.py
│       ├── utils/
│       │   └── helpers.py
│       └── api/
│           └── server.py
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
├── examples/
└── scripts/
```

## How to Contribute

### Reporting Bugs

1. Check existing issues first
2. Create a new issue with:
   - Clear title
   - Description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details

### Suggesting Features

1. Check existing feature requests
2. Create a new issue with:
   - Clear title
   - Description of the feature
   - Use cases
   - Potential implementation ideas

### Submitting Code

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes
4. Write tests if applicable
5. Update documentation if needed
6. Commit with clear message
7. Push to your fork
8. Submit a pull request

## Coding Standards

### Python Style

- Follow PEP 8
- Use Black for formatting
- Use Ruff for linting
- Maximum line length: 100 characters

### Code Quality

- Write docstrings for all public functions
- Add type hints
- Handle errors gracefully
- Write tests for new functionality

### Example

```python
def detect_sitekey(url: str, proxy: Optional[str] = None) -> Optional[str]:
    """
    Detect Cloudflare Turnstile sitekey from URL.

    Args:
        url: Target URL to detect sitekey from
        proxy: Optional proxy for requests

    Returns:
        Detected sitekey or None if not found

    Raises:
        ValueError: If URL is invalid
    """
    if not url:
        raise ValueError("URL cannot be empty")
    
    # Implementation here
    ...
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=alap_alap

# Run specific test file
pytest tests/unit/test_detector.py

# Run with verbose output
pytest -v
```

### Writing Tests

- Place tests in `tests/unit/` or `tests/integration/`
- Name test files `test_*.py`
- Name test functions `test_*`
- Use descriptive test names
- Mock external dependencies

### Test Structure

```python
import pytest
from alap_alap.detector import SitekeyDetector

class TestSitekeyDetector:
    def test_detect_from_url(self):
        """Test sitekey detection from URL parameters."""
        detector = SitekeyDetector()
        # Test implementation
        pass

    def test_invalid_url(self):
        """Test handling of invalid URLs."""
        detector = SitekeyDetector()
        # Test implementation
        pass
```

## Pull Request Process

### Before Submitting

1. Ensure all tests pass
2. Update documentation if needed
3. Add changelog entry
4. Rebase on latest main branch

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] Added tests for new functionality
- [ ] Updated documentation

## Checklist
- [ ] Code follows project style
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Review Process

1. PR will be reviewed by maintainers
2. Address any feedback
3. Once approved, PR will be merged

## Issue Guidelines

### Bug Reports

- Use bug report template
- Include reproduction steps
- Provide environment details
- Attach screenshots if applicable

### Feature Requests

- Use feature request template
- Describe use case
- Explain expected behavior
- Consider implementation complexity

## Questions?

Feel free to open an issue for any questions about contributing.
