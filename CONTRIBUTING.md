# Contributing to Wardrobe

Thank you for your interest in contributing to Wardrobe! We welcome all contributions — from bug reports and feature ideas to documentation improvements and code pull requests.

---

## 🛠️ Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/Kushkc007/Wardrobe.git
   cd Wardrobe
   ```

2. **Set up a Python virtual environment (Python 3.10+):**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux / macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the dashboard locally:**
   ```bash
   python organize.py dashboard
   ```
   Open `http://127.0.0.1:8765` in your browser.

---

## 🌟 Areas We'd Love Help With

- **Semantic Document Deduplication:** Detecting duplicates across different formats (e.g., matching a PDF invoice with its Word `.docx` original).
- **Audio Tagging:** Reading ID3 tags for music metadata (Artist, Album, Year).
- **Local Embedding Support:** Optional `sentence-transformers` for zero-shot text classification.
- **UI Enhancements:** Additional theme customization or keyboard navigation shortcuts.

---

## 📝 Submitting a Pull Request

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Commit your changes with clear, descriptive messages: `git commit -m "Add feature X"`
3. Push to your fork: `git push origin feature/your-feature-name`
4. Open a Pull Request against the `main` branch on GitHub.

We review pull requests promptly. Thank you for making Wardrobe better!
