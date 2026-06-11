# Placement Portal Application
A web app for managing campus placements built with Flask, Vue.js, SQLite, Redis, and Celery.

## Features
- **Authentication**: JWT‑based login for all roles.
- **Admin**: Manage companies, placement drives, and students, approve/reject registrations and view statistics.
- **Company**: Create and manage placement drives, view applicants, shortlist/select/reject candidates.
- **Student**: View eligible approved drives, apply for drives, track application statuses, edit profile.

## Setup & Use
1. Create virtual environment: `python -m venv venv`
2. Activate it: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac/Linux)
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python app.py`
5. Open http://localhost:5000 in your browser.

## Login Credentials
| Role     | Email               | Password   |
|----------|---------------------|------------|
| Admin    | admin@portal.com    | admin123   |
| Student 1| student1@portal.com | pass123    |
| Student 2| student2@portal.com | pass123    |
| Company 1| hr1@portal.com      | pass123    |
| Company 2| hr2@portal.com      | pass123    |
