# Placement Portal Application
A web app for managing campus placements built with Flask, Vue.js, SQLite, Redis, and Celery.

## Features
- **Authentication**: JWT‑based login for all roles.
- **Admin**: Manage companies, placement drives, and students, approve/reject registrations and view statistics.
- **Company**: Create and manage placement drives, view applicants, shortlist/select/reject candidates.
- **Student**: View eligible approved drives, apply for drives, track application statuses, edit profile.
- **Validation** - Data validation is done in both client-side (HTML and JavaScript) and server-side (Flask).
- **Security** - Security of the system is ensured uding JWT Tokens, password hashing, duplicate prevention, eligibility checks and input sanitization.

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

## Online Resources Used
1. https://coolors.co/ (Colour Palette)
2. https://getbootstrap.com/docs/5.0/getting-started/introduction/ (Bootstrap Documentation)
3. https://www.w3schools.com/bootstrap5/index.php (Bootstrap Tutorial)
4. https://flask.palletsprojects.com/en/stable/ (Flask Documentation)
5. https://flask-sqlalchemy.readthedocs.io/en/stable/ (Flask-SQLAlchemy Documentation)
6. https://werkzeug.palletsprojects.com/en/stable/ (Werkzeug Documentation)
7. https://vuejs.org/guide/introduction (Vue.js Documentation)
8. https://docs.celeryq.dev/en/stable/ (Celery Documentation)
9. https://flask-jwt-extended.readthedocs.io/en/stable/ (Flask-JWT-Extended Documentation)
