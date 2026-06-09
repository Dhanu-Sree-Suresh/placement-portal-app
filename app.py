from datetime import datetime

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///placement.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = "jwt-secret"
app.config["ADMIN_EMAIL"] = "admin@portal.com"
app.config["ADMIN_PASSWORD"] = "admin123"
app.config["CACHE_TYPE"] = "RedisCache"
app.config["CACHE_REDIS_URL"] = "redis://localhost:6379/0"
app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/1"
app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/2"


db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created = db.Column(db.DateTime, default=datetime.now)

    company = db.relationship("Company", backref="user", uselist=False)
    student = db.relationship("Student", backref="user", uselist=False)

    def set_password(self, p):
        self.password = generate_password_hash(p)

    def check_password(self, p):
        return check_password_hash(self.password, p)


class Company(db.Model):
    __tablename__ = "company"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    name = db.Column(db.String(200), nullable=False)
    industry = db.Column(db.String(200))
    location = db.Column(db.String(500))
    description = db.Column(db.Text)
    website = db.Column(db.String(500))
    hr_contact = db.Column(db.String(200))
    approved = db.Column(db.Boolean, default=False)

    drives = db.relationship("PlacementDrive", backref="company", lazy=True)


class Student(db.Model):
    __tablename__ = "student"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    name = db.Column(db.String(200), nullable=False)
    roll_number = db.Column(db.String(50), unique=True)
    branch = db.Column(db.String(200))
    cgpa = db.Column(db.Float)
    year = db.Column(db.Integer)
    resume_path = db.Column(db.String(500))
    skills = db.Column(db.String(500))

    applications = db.relationship("Application", backref="student", lazy=True)


class PlacementDrive(db.Model):
    __tablename__ = "placement_drive"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    eligibility = db.Column(db.Text)
    deadline = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.now)

    applications = db.relationship("Application", backref="drive", lazy=True)


class Application(db.Model):
    __tablename__ = "application"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    drive_id = db.Column(
        db.Integer, db.ForeignKey("placement_drive.id"), nullable=False
    )
    status = db.Column(db.String(20), default="applied")
    applied_date = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint("student_id", "drive_id", name="unique_application"),
    )


with app.app_context():
    db.create_all()
    if not User.query.filter_by(role="admin").first():
        admin_user = User(email=app.config["ADMIN_EMAIL"], role="admin")
        admin_user.set_password(app.config["ADMIN_PASSWORD"])
        db.session.add(admin_user)
        db.session.commit()
        print("Default admin created: admin@portal.com / admin123")


@app.route("/")
def index():
    return "Placement Portal is running!"


if __name__ == "__main__":
    app.run(debug=True)
