# ECHO – AI-Powered Personal Memory Assistant

> **Capture once. Remember automatically.**

ECHO is a local web application that helps you remember important things such as warranty expiry dates, food best-before dates, subscription renewals, document expiries, receipts, and medicine refills.

It uses Optical Character Recognition (OCR), TF-IDF feature extraction, Logistic Regression classification, information extraction, and rule-based reasoning to identify important information and generate smart reminders.

## Features
- Scan images or enter text in demo mode.
- Classify memories into seven categories.
- Extract important dates and information.
- Generate category-based reminders.
- Store memories locally using SQLite.
- View, search, and manage saved memories.
- Ask ECHO questions about upcoming reminders.
- Run locally without paid APIs.

## Technologies Used
- Python and Flask
- HTML, CSS, and JavaScript
- Tesseract OCR
- TF-IDF and Logistic Regression
- scikit-learn
- SQLite

## Run the Project

1. Install Python 3.10 or newer.
2. Open the project folder in VS Code.
3. Activate your virtual environment.
4. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Start the application:

   ```powershell
   python app.py
   ```

6. Open `http://127.0.0.1:5000` in your browser.

**Note:** Install Tesseract OCR separately to enable real image scanning. Demo text mode can work without it.

## Privacy

ECHO is designed as a local prototype. Memories are stored in a local SQLite database, and images are processed on your computer.

## Future Improvements
- Desktop and email notifications
- Multilingual OCR
- Export and calendar integration
- Optional database encryption
- Multi-user authentication
