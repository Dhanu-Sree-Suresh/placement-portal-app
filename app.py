"""
Author: Dhanu Sree Suresh (24F2002559)
Placement Portal Application
"""

import base64
import csv
import json
import os
import random
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import StringIO

from celery import Celery, Task
from celery.schedules import crontab
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_caching import Cache
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# initializing Flask application instance
app = Flask(__name__)

# conventionally, in a real world scenario in production, this is not commited to the code. it is usually added as a 'secret' and is hidden
# also, we usually have a random string for the same usually
# additionally, in production, each constituent part is separated; however, for the purpose of this project, a monolithic approach has been used
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
app.config["UPLOAD_FOLDER"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "uploads"
)

# initializing SQLAlchemy database, JWTManager and Cache
db = SQLAlchemy(app)
jwt = JWTManager(app)
cache = Cache(app)

SMTP_HOST = "localhost"
SMTP_PORT = 1025
SENDER_EMAIL = "placement@portal.com"
SENDER_PASSWORD = ""

celery_app = Celery(
    "app",
    broker=app.config["CELERY_BROKER_URL"],
    backend=app.config["CELERY_RESULT_BACKEND"],
)


class FlaskTask(Task):
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)


celery_app.Task = FlaskTask

celery_app.conf.timezone = "Asia/Dubai"
celery_app.conf.beat_schedule = {
    "daily-reminders": {
        "task": "app.send_daily_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    "monthly-report": {
        "task": "app.generate_monthly_report",
        "schedule": crontab(hour=0, minute=0, day_of_month=1),
    },
}

# categories for reviewing
INTERVIEW_CATEGORIES = ["process", "difficulty"]
COMPANY_CATEGORIES = [
    "culture",
    "compensation",
    "career",
    "work_life",
    "senior_mgmt",
    "diversity",
    "process",
    "difficulty",
]


# helper function to send mail using SMTP
def send_email(to, subject, body, content_type="text", attachment=None):
    msg = MIMEMultipart()
    msg["To"] = to
    msg["From"] = SENDER_EMAIL
    msg["Subject"] = subject
    if content_type == "html":
        msg.attach(MIMEText(body, "html"))
    else:
        msg.attach(MIMEText(body, "plain"))
    if attachment:
        fn, fc, ft = attachment
        att = MIMEText(fc, "csv")
        att.add_header("Content-Disposition", "attachment", filename=fn)
        msg.attach(att)
    s = smtplib.SMTP(host=SMTP_HOST, port=SMTP_PORT)
    s.login(SENDER_EMAIL, SENDER_PASSWORD)
    s.send_message(msg)
    s.quit()


# function used to ensure that datetime format is consistent across the application
def format_dt(dt):
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M")
    return None


# function used to parse skills for ATS scanner
def split_skills(skills_str):
    if not skills_str:
        return []
    return [s.strip() for s in skills_str.replace(",", " ").split() if s.strip()]


# user model
class User(db.Model):
    __tablename__ = "user"
    u_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_blacklisted = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=datetime.now)

    # uselist=False means we are creating a one-to-one realtionship; by default this value is True meaning one-to-many or many-to-many relationship
    company = db.relationship("Company", backref="user", uselist=False)
    student = db.relationship("Student", backref="user", uselist=False)

    # creaiting password setter and checker for hashed passwords to ensure security
    def set_password(self, p):
        self.password = generate_password_hash(p)

    def check_password(self, p):
        return check_password_hash(self.password, p)


# company model representing registered companies
class Company(db.Model):
    __tablename__ = "company"
    c_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.u_id"), unique=True, nullable=False
    )
    name = db.Column(db.String(200), nullable=False)
    industry = db.Column(db.String(200))
    location = db.Column(db.String(500))
    description = db.Column(db.Text)
    website = db.Column(db.String(500))
    hr_contact = db.Column(db.String(200))
    approved = db.Column(db.Boolean, default=False)

    drives = db.relationship("PlacementDrive", backref="company", lazy=True)
    reviews = db.relationship("Review", backref="company", lazy=True)


# student model representing student users
class Student(db.Model):
    __tablename__ = "student"
    s_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.u_id"), unique=True, nullable=False
    )
    name = db.Column(db.String(200), nullable=False)
    roll_number = db.Column(db.String(50), unique=True)
    branch = db.Column(db.String(200))
    cgpa = db.Column(db.Float)
    year = db.Column(db.Integer)
    resume_path = db.Column(db.String(500))
    skills = db.Column(db.String(500))

    applications = db.relationship("Application", backref="student", lazy=True)
    reviews = db.relationship("Review", backref="student", lazy=True)


# placement drive model representing placement opportunities
class PlacementDrive(db.Model):
    __tablename__ = "placement_drive"
    p_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.c_id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    branch = db.Column(db.String(200))
    cgpa_min = db.Column(db.Float)
    year = db.Column(db.String(200))
    deadline = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.now)
    required_skills = db.Column(db.Text)
    preferred_skills = db.Column(db.Text)
    technologies = db.Column(db.String(500))
    experience = db.Column(db.String(100))
    closed_by_admin = db.Column(db.Boolean, default=False)  # NEW

    applications = db.relationship("Application", backref="drive", lazy=True)


# application model representing student job applications
class Application(db.Model):
    __tablename__ = "application"
    a_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.s_id"), nullable=False)
    drive_id = db.Column(
        db.Integer, db.ForeignKey("placement_drive.p_id"), nullable=False
    )
    status = db.Column(db.String(20), default="applied")
    applied_date = db.Column(db.DateTime, default=datetime.now)
    package = db.Column(db.String(50))
    placement_date = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("student_id", "drive_id", name="unique_application"),
    )


# review model representing company and interview reviews
class Review(db.Model):
    __tablename__ = "review"
    r_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.s_id"), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey("company.c_id"), nullable=False)
    drive_id = db.Column(
        db.Integer, db.ForeignKey("placement_drive.p_id"), nullable=True
    )
    review_type = db.Column(db.String(20), nullable=False)
    sub_ratings = db.Column(db.Text)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "company_id", "review_type", name="unique_review_per_type"
        ),
    )


# function to create sample data for application on application startup
def sample_data():
    if User.query.filter_by(role="student").first():
        return

    s_users = []
    s_data = [
        (
            "student1@portal.com",
            "Student One",
            "10001",
            "CS",
            8.5,
            2024,
            "Python, Flask, JavaScript, React",
        ),
        (
            "student2@portal.com",
            "Student Two",
            "10002",
            "EE",
            7.8,
            2024,
            "C++, MATLAB, Embedded Systems",
        ),
        (
            "student3@portal.com",
            "Student Three",
            "10003",
            "ME",
            7.2,
            2025,
            "SolidWorks, ANSYS, Python",
        ),
        (
            "student4@portal.com",
            "Student Four",
            "10004",
            "CS",
            9.1,
            2024,
            "Java, Spring Boot, SQL, AWS",
        ),
        (
            "student5@portal.com",
            "Student Five",
            "10005",
            "EC",
            8.0,
            2025,
            "VHDL, Verilog, C, Python",
        ),
        (
            "student6@portal.com",
            "Student Six",
            "10006",
            "CS",
            7.5,
            2024,
            "Python, Django, HTML, CSS",
        ),
        (
            "student7@portal.com",
            "Student Seven",
            "10007",
            "EE",
            8.2,
            2024,
            "Power Systems, MATLAB, C",
        ),
        (
            "student8@portal.com",
            "Student Eight",
            "10008",
            "ME",
            7.9,
            2025,
            "AutoCAD, CATIA, Python",
        ),
        (
            "student9@portal.com",
            "Student Nine",
            "10009",
            "CS",
            8.8,
            2024,
            "React, Node.js, MongoDB, TypeScript",
        ),
        (
            "student10@portal.com",
            "Student Ten",
            "10010",
            "EC",
            7.4,
            2025,
            "IoT, Arduino, Python, C++",
        ),
        (
            "student11@portal.com",
            "Student Eleven",
            "10011",
            "CS",
            8.3,
            2024,
            "Python, Machine Learning, TensorFlow",
        ),
        (
            "student12@portal.com",
            "Student Twelve",
            "10012",
            "EE",
            7.6,
            2024,
            "Signal Processing, MATLAB, Python",
        ),
    ]
    for email, name, roll, branch, cgpa, year, skills in s_data:
        u = User(email=email, role="student")
        u.set_password("pass123")
        db.session.add(u)
        db.session.flush()
        s = Student(
            user_id=u.u_id,
            name=name,
            roll_number=roll,
            branch=branch,
            cgpa=cgpa,
            year=year,
            skills=skills,
        )
        db.session.add(s)
        s_users.append(s)

    c_users = []
    c_data = [
        (
            "hr1@portal.com",
            "TechNova Solutions",
            "IT",
            "Bangalore, Karnataka",
            "Leading software company",
            "www.technova.com",
            "+91 9876543210",
            True,
        ),
        (
            "hr2@portal.com",
            "AnalyticsHub",
            "Analytics",
            "Mumbai, Maharashtra",
            "Data analytics firm",
            "www.analyticshub.com",
            "+91 9123456780",
            False,
        ),
        (
            "hr3@portal.com",
            "CloudPeak Systems",
            "Cloud Computing",
            "Hyderabad, Telangana",
            "Cloud infrastructure provider",
            "www.cloudpeak.com",
            "+91 9988776655",
            True,
        ),
        (
            "hr4@portal.com",
            "FinEdge Technologies",
            "FinTech",
            "Pune, Maharashtra",
            "Financial technology solutions",
            "www.finedge.com",
            "+91 8877665544",
            True,
        ),
        (
            "hr5@portal.com",
            "GreenEnergy Corp",
            "Renewable Energy",
            "Delhi, NCR",
            "Sustainable energy solutions",
            "www.greenenergycorp.com",
            "+91 7766554433",
            False,
        ),
        (
            "hr6@portal.com",
            "MediCare Innovations",
            "Healthcare",
            "Chennai, Tamil Nadu",
            "Healthcare technology",
            "www.medicareinnov.com",
            "+91 6655443322",
            True,
        ),
        (
            "hr7@portal.com",
            "EduTech Global",
            "Education",
            "Kolkata, West Bengal",
            "E-learning platform",
            "www.edutechglobal.com",
            "+91 5544332211",
            True,
        ),
        (
            "hr8@portal.com",
            "AutoDrive Motors",
            "Automotive",
            "Ahmedabad, Gujarat",
            "Electric vehicle manufacturer",
            "www.autodrivemotors.com",
            "+91 4433221100",
            True,
        ),
    ]
    for email, name, ind, loc, desc, web, hr, appr in c_data:
        u = User(email=email, role="company")
        u.set_password("pass123")
        if email == "hr5@portal.com":
            u.is_active = False
        db.session.add(u)
        db.session.flush()
        c = Company(
            user_id=u.u_id,
            name=name,
            industry=ind,
            location=loc,
            description=desc,
            website=web,
            hr_contact=hr,
            approved=appr,
        )
        db.session.add(c)
        c_users.append(c)

    db.session.flush()

    drives_data = [
        (
            c_users[0].c_id,
            "Software Engineer",
            "Develop scalable web applications",
            "CS,IT",
            7.0,
            "2024,2025",
            datetime.now() + timedelta(days=30),
            "approved",
            "Python,JavaScript,React",
            "Docker,AWS",
            "React,Node.js,PostgreSQL",
            "0-2 years",
        ),
        (
            c_users[0].c_id,
            "Data Analyst",
            "Analyze business data",
            "CS,EC,EE",
            7.5,
            "2024,2025",
            datetime.now() + timedelta(days=15),
            "approved",
            "Python,SQL,Statistics",
            "Tableau,PowerBI",
            "Python,Pandas,NumPy",
            "0-1 year",
        ),
        (
            c_users[2].c_id,
            "Cloud Engineer",
            "Manage cloud infrastructure",
            "CS,IT,EC",
            7.5,
            "2024",
            datetime.now() + timedelta(days=45),
            "approved",
            "AWS,Linux,Networking",
            "Terraform,Kubernetes",
            "AWS,Azure,GCP",
            "1-3 years",
        ),
        (
            c_users[2].c_id,
            "DevOps Intern",
            "CI/CD pipeline management",
            "CS,IT",
            8.0,
            "2025",
            datetime.now() + timedelta(days=20),
            "pending",
            "Git,Jenkins,Docker",
            "Kubernetes,Ansible",
            "Linux,Bash,Python",
            "0-1 year",
        ),
        (
            c_users[3].c_id,
            "Full Stack Developer",
            "End-to-end application development",
            "CS,IT",
            7.5,
            "2024,2025",
            datetime.now() + timedelta(days=25),
            "approved",
            "JavaScript,React,Node.js",
            "TypeScript,GraphQL",
            "MongoDB,Express,React,Node.js",
            "1-2 years",
        ),
        (
            c_users[3].c_id,
            "Blockchain Developer",
            "Smart contract development",
            "CS,IT",
            8.0,
            "2024",
            datetime.now() + timedelta(days=60),
            "approved",
            "Solidity,Ethereum,JavaScript",
            "Web3.js,Hardhat",
            "Blockchain,Smart Contracts,DeFi",
            "1-3 years",
        ),
        (
            c_users[5].c_id,
            "Healthcare Data Scientist",
            "Medical data analysis",
            "CS,EC,EE",
            8.0,
            "2024,2025",
            datetime.now() + timedelta(days=35),
            "approved",
            "Python,R,Machine Learning",
            "Healthcare,NLP",
            "TensorFlow,Scikit-learn,Pandas",
            "1-2 years",
        ),
        (
            c_users[5].c_id,
            "Medical Software Tester",
            "Test healthcare applications",
            "CS,IT,EC",
            7.0,
            "2024,2025",
            datetime.now() + timedelta(days=10),
            "approved",
            "Testing,Selenium,Python",
            "JMeter,Postman",
            "Automation,Manual Testing",
            "0-2 years",
        ),
        (
            c_users[6].c_id,
            "EdTech Content Developer",
            "Create educational content",
            "CS,EC,ME",
            7.0,
            "2024,2025",
            datetime.now() + timedelta(days=40),
            "approved",
            "Python,JavaScript,Teaching",
            "Articulate,Captivate",
            "Curriculum Design,eLearning",
            "0-1 year",
        ),
        (
            c_users[7].c_id,
            "Embedded Systems Engineer",
            "Develop automotive embedded software",
            "EE,EC,CS",
            7.5,
            "2024",
            datetime.now() + timedelta(days=50),
            "approved",
            "C,C++,Embedded C",
            "RTOS,MATLAB",
            "Microcontrollers,ARM,CAN",
            "1-3 years",
        ),
        (
            c_users[7].c_id,
            "Automotive Designer",
            "Design vehicle components",
            "ME",
            7.0,
            "2025",
            datetime.now() + timedelta(days=55),
            "pending",
            "CATIA,SolidWorks",
            "ANSYS,GD&T",
            "CAD,CAE,FEA",
            "0-2 years",
        ),
        (
            c_users[0].c_id,
            "Mobile App Developer",
            "Build cross-platform mobile apps",
            "CS,IT",
            7.5,
            "2024,2025",
            datetime.now() + timedelta(days=5),
            "approved",
            "Flutter,Dart,Firebase",
            "React Native,Swift",
            "iOS,Android,Cross-platform",
            "0-2 years",
        ),
        (
            c_users[2].c_id,
            "Cybersecurity Analyst",
            "Security monitoring and analysis",
            "CS,IT,EC",
            8.0,
            "2024",
            datetime.now() + timedelta(days=70),
            "approved",
            "Networking,Security+,Python",
            "CEH,CISSP",
            "SIEM,Penetration Testing",
            "1-3 years",
        ),
        (
            c_users[3].c_id,
            "AI/ML Engineer",
            "Machine learning model development",
            "CS,IT",
            8.5,
            "2024,2025",
            datetime.now() + timedelta(days=80),
            "approved",
            "Python,TensorFlow,PyTorch",
            "NLP,Computer Vision",
            "Deep Learning,MLOps,Kubeflow",
            "1-2 years",
        ),
        (
            c_users[5].c_id,
            "Health Informatics Specialist",
            "Healthcare data management",
            "CS,IT,EC",
            7.0,
            "2024,2025",
            datetime.now() + timedelta(days=65),
            "closed",
            "SQL,Python,Healthcare IT",
            "HL7,FHIR",
            "EHR,Data Analytics",
            "1-2 years",
        ),
    ]
    drives = []
    for (
        comp_id,
        title,
        desc,
        branch,
        cgpa,
        yr,
        dead,
        stat,
        req,
        pref,
        tech,
        exp,
    ) in drives_data:
        d = PlacementDrive(
            company_id=comp_id,
            title=title,
            description=desc,
            branch=branch,
            cgpa_min=cgpa,
            year=yr,
            deadline=dead,
            status=stat,
            required_skills=req,
            preferred_skills=pref,
            technologies=tech,
            experience=exp,
        )
        db.session.add(d)
        drives.append(d)

    db.session.flush()

    app_data = [
        (
            s_users[0].s_id,
            drives[0].p_id,
            "selected",
            "18 LPA",
            datetime.now() - timedelta(days=90),
        ),
        (s_users[0].s_id, drives[2].p_id, "shortlisted", None, None),
        (s_users[1].s_id, drives[0].p_id, "rejected", None, None),
        (s_users[1].s_id, drives[2].p_id, "applied", None, None),
        (s_users[2].s_id, drives[0].p_id, "applied", None, None),
        (
            s_users[3].s_id,
            drives[0].p_id,
            "selected",
            "22 LPA",
            datetime.now() - timedelta(days=60),
        ),
        (s_users[3].s_id, drives[4].p_id, "shortlisted", None, None),
        (s_users[3].s_id, drives[6].p_id, "applied", None, None),
        (s_users[4].s_id, drives[2].p_id, "rejected", None, None),
        (s_users[4].s_id, drives[9].p_id, "applied", None, None),
        (
            s_users[5].s_id,
            drives[0].p_id,
            "selected",
            "15 LPA",
            datetime.now() - timedelta(days=45),
        ),
        (s_users[5].s_id, drives[4].p_id, "applied", None, None),
        (s_users[6].s_id, drives[2].p_id, "applied", None, None),
        (s_users[6].s_id, drives[9].p_id, "shortlisted", None, None),
        (s_users[7].s_id, drives[10].p_id, "applied", None, None),
        (
            s_users[8].s_id,
            drives[0].p_id,
            "selected",
            "25 LPA",
            datetime.now() - timedelta(days=30),
        ),
        (s_users[8].s_id, drives[4].p_id, "shortlisted", None, None),
        (s_users[8].s_id, drives[13].p_id, "applied", None, None),
        (s_users[9].s_id, drives[2].p_id, "applied", None, None),
        (
            s_users[10].s_id,
            drives[0].p_id,
            "selected",
            "20 LPA",
            datetime.now() - timedelta(days=75),
        ),
        (s_users[10].s_id, drives[13].p_id, "shortlisted", None, None),
        (
            s_users[11].s_id,
            drives[2].p_id,
            "selected",
            "19 LPA",
            datetime.now() - timedelta(days=50),
        ),
        (s_users[11].s_id, drives[9].p_id, "rejected", None, None),
    ]
    for sid, did, stat, pkg, pdate in app_data:
        a = Application(
            student_id=sid,
            drive_id=did,
            status=stat,
            package=pkg,
            placement_date=pdate,
            applied_date=datetime.now() - timedelta(days=random.randint(5, 100)),
        )
        db.session.add(a)

    db.session.flush()

    review_data = [
        (
            s_users[0].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "company",
            {
                "culture": 5,
                "compensation": 4,
                "career": 5,
                "work_life": 4,
                "senior_mgmt": 4,
                "diversity": 5,
                "process": 4,
                "difficulty": 3,
            },
            "Great place to work",
        ),
        (
            s_users[0].s_id,
            c_users[2].c_id,
            drives[2].p_id,
            "interview",
            {"process": 4, "difficulty": 4},
            "Challenging but fair",
        ),
        (
            s_users[3].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "company",
            {
                "culture": 4,
                "compensation": 5,
                "career": 4,
                "work_life": 3,
                "senior_mgmt": 4,
                "diversity": 4,
                "process": 5,
                "difficulty": 3,
            },
            "Good compensation",
        ),
        (
            s_users[3].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "interview",
            {"process": 5, "difficulty": 3},
            "Smooth process",
        ),
        (
            s_users[5].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "company",
            {
                "culture": 5,
                "compensation": 4,
                "career": 5,
                "work_life": 5,
                "senior_mgmt": 5,
                "diversity": 4,
                "process": 4,
                "difficulty": 2,
            },
            "Amazing culture",
        ),
        (
            s_users[5].s_id,
            c_users[3].c_id,
            drives[4].p_id,
            "interview",
            {"process": 3, "difficulty": 5},
            "Very tough technical round",
        ),
        (
            s_users[8].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "company",
            {
                "culture": 4,
                "compensation": 5,
                "career": 4,
                "work_life": 4,
                "senior_mgmt": 3,
                "diversity": 5,
                "process": 4,
                "difficulty": 3,
            },
            "Great learning experience",
        ),
        (
            s_users[10].s_id,
            c_users[0].c_id,
            drives[0].p_id,
            "company",
            {
                "culture": 5,
                "compensation": 5,
                "career": 5,
                "work_life": 4,
                "senior_mgmt": 4,
                "diversity": 5,
                "process": 5,
                "difficulty": 4,
            },
            "Best company ever",
        ),
        (
            s_users[11].s_id,
            c_users[2].c_id,
            drives[2].p_id,
            "company",
            {
                "culture": 4,
                "compensation": 4,
                "career": 4,
                "work_life": 4,
                "senior_mgmt": 3,
                "diversity": 4,
                "process": 4,
                "difficulty": 3,
            },
            "Decent workplace",
        ),
    ]

    for sid, cid, did, rtype, sub, com in review_data:
        r = Review(
            student_id=sid,
            company_id=cid,
            drive_id=did,
            review_type=rtype,
            sub_ratings=json.dumps(sub),
            comment=com,
            created_at=datetime.now() - timedelta(days=random.randint(1, 60)),
        )
        db.session.add(r)

    db.session.commit()


with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()
    try:
        db.session.execute(
            text("ALTER TABLE user ADD COLUMN is_blacklisted BOOLEAN DEFAULT 0")
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(
            text(
                "ALTER TABLE placement_drive ADD COLUMN closed_by_admin BOOLEAN DEFAULT 0"
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    if not User.query.filter_by(role="admin").first():
        # creating default admin
        admin_user = User(email=app.config["ADMIN_EMAIL"], role="admin")
        admin_user.set_password(app.config["ADMIN_PASSWORD"])
        db.session.add(admin_user)
        db.session.commit()
        print("Default admin credentials: admin@portal.com | admin123")

    sample_data()


# function to verify user role
def check_role(role):
    j = get_jwt()
    if j.get("role") != role:
        return jsonify(msg="Access Forbidden for Role"), 403
    else:
        return None


# function to verify if user is active and is not blacklisted
def check_user_status():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(msg="User not found"), 404
    if user.is_blacklisted:
        return jsonify(msg="Your account has been blacklisted."), 403
    if request.method in ["POST", "PUT", "DELETE"] and not user.is_active:
        return jsonify(
            msg="Your account is deactivated. You cannot perform this action."
        ), 403
    return None


# function to verify email format using regex additionally
def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)


# function to compute rating for company based on reviews
def compute_company_ratings(company_id):
    r = Review.query.filter_by(company_id=company_id).all()
    interview_revs = [rv for rv in r if rv.review_type == "interview"]
    company_revs = [rv for rv in r if rv.review_type == "company"]

    res = {
        "avg_interview": 0,
        "avg_company": 0,
        "total": len(r),
        "interview_count": len(interview_revs),
        "company_count": len(company_revs),
        "categories": {},
    }

    cat_sums = {}
    cat_counts = {}
    interview_sum = 0.0
    interview_count = 0
    company_sum = 0.0
    company_count = 0

    for i in r:
        sub = {}
        if i.sub_ratings:
            try:
                sub = json.loads(i.sub_ratings)
            except:
                pass
        if i.review_type == "interview":
            process = sub.get("process", 0)
            difficulty = sub.get("difficulty", 0)
            if process > 0:
                interview_sum += process
                interview_count += 1
            for k in ["process", "difficulty"]:
                val = sub.get(k, 0)
                if val > 0:
                    cat_sums[k] = cat_sums.get(k, 0) + val
                    cat_counts[k] = cat_counts.get(k, 0) + 1
        else:
            total_company_rating = 0.0
            total_company_items = 0
            for cat in COMPANY_CATEGORIES:
                val = sub.get(cat, 0)
                if val > 0:
                    cat_sums[cat] = cat_sums.get(cat, 0) + val
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    if cat != "difficulty":
                        total_company_rating += val
                        total_company_items += 1
            if total_company_items > 0:
                company_sum += total_company_rating / total_company_items
                company_count += 1

    if interview_count:
        res["avg_interview"] = round(interview_sum / interview_count, 1)
    if company_count:
        res["avg_company"] = round(company_sum / company_count, 1)

    cats = {}
    for k, v in cat_sums.items():
        if cat_counts[k]:
            cats[k] = round(v / cat_counts[k], 1)
    res["categories"] = cats

    return res


# sends daily reminders for drives with upcoming deadlines (scheduled for 8.00 AM per day and send the reminders for drives with deadlines within the next 24 hours)
@celery_app.task
def send_daily_reminders():
    tom = datetime.now() + timedelta(days=1)
    dr = PlacementDrive.query.filter(
        PlacementDrive.status == "approved",
        PlacementDrive.deadline >= datetime.now(),
        PlacementDrive.deadline <= tom + timedelta(days=1),
    ).all()
    for d in dr:
        st = Student.query.all()
        for s in st:
            if not Application.query.filter_by(
                student_id=s.s_id, drive_id=d.p_id
            ).first():
                send_email(
                    s.user.email,
                    "Upcoming Placement Drive Deadline",
                    f"Dear {s.name},\n\nThe application deadline for '{d.title}' is approaching. Kindly apply now.",
                )
    return "Daily reminders sent"


# sends monthly placement summary report to admin
@celery_app.task
def generate_monthly_report():
    now = datetime.now()
    if now.month == 1:
        lm = 12
        y = now.year - 1
    else:
        lm = now.month - 1
        y = now.year
    s = datetime(y, lm, 1)
    e = datetime(y, lm + 1, 1) if lm < 12 else datetime(y + 1, 1, 1)
    dc = PlacementDrive.query.filter(
        PlacementDrive.created_at >= s, PlacementDrive.created_at < e
    ).count()
    apps = Application.query.filter(
        Application.applied_date >= s, Application.applied_date < e
    ).count()
    sel = Application.query.filter(
        Application.applied_date >= s,
        Application.applied_date < e,
        Application.status == "selected",
    ).count()
    html = f"""
    <html><body>
    <h2>Monthly Placement Report - {s.strftime("%B %Y")}</h2>
    <p>Drives Conducted: {dc}</p>
    <p>Applications Received: {apps}</p>
    <p>Students Selected: {sel}</p>
    </body></html>
    """
    send_email(
        app.config["ADMIN_EMAIL"],
        "Monthly Placement Report",
        html,
        content_type="html",
    )
    return "Monthly report sent"


# sends CSV of student's application history to their email
@celery_app.task
def export_student_csv_task(student_id):
    s = Student.query.get(student_id)
    if not s:
        return "Student not found"
    apps = Application.query.filter_by(student_id=student_id).all()
    l = ["Student ID,Company,Drive Title,Status,Date"]
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        l.append(f"{s.s_id},{c.name},{d.title},{a.status},{format_dt(a.applied_date)}")
    csv_content = "\n".join(l)
    send_email(
        s.user.email,
        "Your Application History CSV",
        "Please find attached your placement application history.",
        attachment=("applications.csv", csv_content, "text/csv"),
    )
    return f"CSV sent to {s.user.email}"


# sends email on application status to student (offer letter on selection and normal emails on shortlisting and rejection)
@celery_app.task
def send_application_status_email(student_id, drive_id, status):
    s = Student.query.get(student_id)
    d = PlacementDrive.query.get(drive_id)
    if not s or not d:
        return
    if status == "selected":
        subject = f"Congratulations! You have been selected for {d.title}"
        body = f"""
        <html><body>
        <h2>Offer Letter</h2>
        <p>Dear {s.name},</p>
        <p>We are pleased to inform you that you have been selected for the position of <strong>{d.title}</strong> at <strong>{d.company.name}</strong>.</p>
        <p>Please contact {d.company.hr_contact or "HR"} for further details.</p>
        </body></html>
        """
        send_email(s.user.email, subject, body, content_type="html")
    elif status == "rejected":
        subject = f"Application Status for {d.title}"
        body = f"Dear {s.name},\n\nWe regret to inform you that your application for '{d.title}' has not been successful at this time.\n\nThank you for your interest."
        send_email(s.user.email, subject, body)
    elif status == "shortlisted":
        subject = f"You have been shortlisted for {d.title}"
        body = f"Dear {s.name},\n\nCongratulations! You have been shortlisted for '{d.title}'. Please wait for further instructions."
        send_email(s.user.email, subject, body)


def invalidate_admin_caches():
    redis_client = cache.cache._write_client
    for pattern in [
        "admin_dashboard",
        "admin_companies_*",
        "admin_drives_*",
        "admin_students_*",
    ]:
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)


# user authentication route
@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
    if not d.get("email") or not d.get("password"):
        return jsonify(msg="Email and password required"), 400
    u = User.query.filter_by(email=d.get("email")).first()
    if not u or not u.check_password(d.get("password")):
        return jsonify(msg="Invalid Email or Password"), 401
    if u.is_blacklisted:
        return jsonify(msg="Your account has been blacklisted. Contact admin."), 403
    r = {"role": u.role}
    a = create_access_token(identity=str(u.u_id), additional_claims=r)
    return jsonify(access_token=a, role=u.role)


# registration route for student
@app.route("/api/register/student", methods=["POST"])
def register_student():
    d = request.get_json()
    if not d.get("email") or not d.get("password") or not d.get("name"):
        return jsonify(msg="Missing required fields (email, password, name)"), 400
    if not is_valid_email(d["email"]):
        return jsonify(msg="Invalid email format"), 400
    if User.query.filter_by(email=d["email"]).first():
        return jsonify(msg="Email already registered"), 400
    cgpa = d.get("cgpa")
    if cgpa is not None:
        try:
            cgpa = float(cgpa)
            if cgpa < 0 or cgpa > 10:
                return jsonify(msg="CGPA must be between 0 and 10"), 400
        except (ValueError, TypeError):
            return jsonify(msg="Invalid CGPA"), 400
    year = d.get("year")
    if year is not None:
        try:
            year = int(year)
        except (ValueError, TypeError):
            return jsonify(msg="Invalid graduation year"), 400
    u = User(email=d["email"].strip().lower(), role="student")
    u.set_password(d["password"])
    db.session.add(u)
    db.session.flush()

    s = Student(
        user_id=u.u_id,
        name=d["name"].strip(),
        roll_number=d.get("roll_number", "").strip() or None,
        branch=d.get("branch", "").strip() or None,
        cgpa=cgpa,
        year=year,
        skills=d.get("skills", "").strip() or None,
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(msg="Student Registered."), 201


# registration route for companies
@app.route("/api/register/company", methods=["POST"])
def register_company():
    d = request.get_json()
    if not d.get("email") or not d.get("password") or not d.get("name"):
        return jsonify(
            msg="Missing required fields (email, password, company name)"
        ), 400
    if not is_valid_email(d["email"]):
        return jsonify(msg="Invalid email format"), 400
    if User.query.filter_by(email=d["email"]).first():
        return jsonify(msg="Email already registered"), 400
    u = User(email=d["email"].strip().lower(), role="company")
    u.set_password(d["password"])
    db.session.add(u)
    db.session.flush()

    c = Company(
        user_id=u.u_id,
        name=d["name"].strip(),
        industry=d.get("industry", "").strip() or None,
        location=d.get("location", "").strip() or None,
        description=d.get("description", "").strip() or None,
        website=d.get("website", "").strip() or None,
        hr_contact=d.get("hr_contact", "").strip() or None,
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(msg="Company Registered. Approval Pending"), 201


# admin dashboard route
@app.route("/api/admin/dashboard")
@jwt_required()
@cache.cached(timeout=60, key_prefix="admin_dashboard")
def admin_dashboard():
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    t_s = Student.query.count()
    t_c = Company.query.filter_by(approved=True).count()
    t_d = PlacementDrive.query.count()
    p_c = Company.query.filter_by(approved=False).count()
    p_d = PlacementDrive.query.filter_by(status="pending").count()

    return jsonify(
        total_students=t_s,
        total_companies=t_c,
        total_drives=t_d,
        pending_companies=p_c,
        pending_drives=p_d,
    )


# admin company related data view
@app.route("/api/admin/companies")
@jwt_required()
@cache.cached(timeout=60, key_prefix=lambda: f"admin_companies_{request.url}")
def admin_list_companies():
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    f = request.args.get("filter", "all")
    query = Company.query
    if f == "approved":
        query = query.filter_by(approved=True)
    elif f == "unapproved":
        query = query.filter_by(approved=False)
    elif f == "active":
        query = query.join(User).filter(
            User.is_active == True, User.is_blacklisted == False
        )
    elif f == "inactive":
        query = query.join(User).filter(
            User.is_active == False, User.is_blacklisted == False
        )
    elif f == "blacklisted":
        query = query.join(User).filter(User.is_blacklisted == True)

    com = query.all()
    res = []
    for c in com:
        u = User.query.get(c.user_id)
        res.append(
            {
                "c_id": c.c_id,
                "name": c.name,
                "email": u.email,
                "approved": c.approved,
                "active": u.is_active,
                "blacklisted": u.is_blacklisted,
                "industry": c.industry,
                "location": c.location,
            }
        )
    return jsonify(res)


@app.route("/api/admin/companies/<int:company_id>")
@jwt_required()
def admin_view_company(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    c = Company.query.get_or_404(company_id)
    u = User.query.get(c.user_id)
    reviews = Review.query.filter_by(company_id=c.c_id).all()
    rev_list = []
    for rv in reviews:
        sub = {}
        if rv.sub_ratings:
            try:
                sub = json.loads(rv.sub_ratings)
            except:
                pass
        rev_list.append(
            {
                "r_id": rv.r_id,
                "review_type": rv.review_type,
                "rating": sum(sub.values()) // max(len(sub), 1) if sub else 0,
                "sub_ratings": sub,
                "comment": rv.comment,
                "date": format_dt(rv.created_at),
            }
        )
    ratings = compute_company_ratings(c.c_id)
    return jsonify(
        c_id=c.c_id,
        name=c.name,
        email=u.email,
        industry=c.industry,
        location=c.location,
        description=c.description,
        website=c.website,
        hr_contact=c.hr_contact,
        approved=c.approved,
        active=u.is_active,
        blacklisted=u.is_blacklisted,
        reviews=rev_list,
        ratings=ratings,
    )


@app.route("/api/admin/companies/<int:company_id>", methods=["PUT"])
@jwt_required()
def admin_edit_company(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    c = Company.query.get_or_404(company_id)
    d = request.get_json()
    if "name" in d:
        c.name = d["name"].strip()
    if "industry" in d:
        c.industry = d["industry"]
    if "location" in d:
        c.location = d["location"]
    if "description" in d:
        c.description = d["description"]
    if "website" in d:
        c.website = d["website"]
    if "hr_contact" in d:
        c.hr_contact = d["hr_contact"]
    if "approved" in d:
        c.approved = d["approved"]
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg="Company updated")


@app.route("/api/admin/companies/<int:company_id>", methods=["DELETE"])
@jwt_required()
def admin_delete_company(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    c = Company.query.get_or_404(company_id)
    user = User.query.get(c.user_id)
    db.session.delete(c)
    if user:
        db.session.delete(user)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg="Company deleted")


@app.route("/api/admin/companies/<int:company_id>/drives")
@jwt_required()
def admin_view_company_drives(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    dr = PlacementDrive.query.filter_by(company_id=company_id).all()
    res = []
    for d in dr:
        res.append(
            {
                "p_id": d.p_id,
                "title": d.title,
                "description": d.description,
                "branch": d.branch,
                "cgpa_min": d.cgpa_min,
                "year": d.year,
                "deadline": format_dt(d.deadline),
                "status": d.status,
                "closed_by_admin": d.closed_by_admin,
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>/applications")
@jwt_required()
def admin_view_drive_applications(drive_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    apps = Application.query.filter_by(drive_id=drive_id).all()
    res = []
    for a in apps:
        student = Student.query.get(a.student_id)
        res.append(
            {
                "a_id": a.a_id,
                "student_name": student.name,
                "roll_number": student.roll_number,
                "branch": student.branch,
                "cgpa": student.cgpa,
                "status": a.status,
                "applied_date": format_dt(a.applied_date),
            }
        )
    return jsonify(res)


@app.route("/api/admin/companies/<int:company_id>/approve", methods=["PUT"])
@jwt_required()
def admin_approve_company(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    c = Company.query.get_or_404(company_id)
    c.approved = True
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg="Company approved")


@app.route("/api/admin/companies/<int:company_id>/reject", methods=["DELETE"])
@jwt_required()
def admin_reject_company(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    c = Company.query.get_or_404(company_id)
    user = User.query.get(c.user_id)
    db.session.delete(c)
    db.session.delete(user)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg="Company Registration Rejected")


@app.route("/api/admin/companies/<int:company_id>/toggle-active", methods=["PUT"])
@jwt_required()
def admin_toggle_company_active(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    c = Company.query.get_or_404(company_id)
    u = User.query.get(c.user_id)
    u.is_active = not u.is_active
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg=f"Company {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/admin/companies/<int:company_id>/toggle-blacklist", methods=["PUT"])
@jwt_required()
def admin_toggle_company_blacklist(company_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    c = Company.query.get_or_404(company_id)
    u = User.query.get(c.user_id)
    u.is_blacklisted = not u.is_blacklisted
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(
        msg=f"Company {'Blacklisted' if u.is_blacklisted else 'Unblacklisted'}"
    )


# admin placement drive related data view
@app.route("/api/admin/drives")
@jwt_required()
@cache.cached(timeout=60, key_prefix=lambda: f"admin_drives_{request.url}")
def admin_list_drives():
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    f = request.args.get("filter", "all")
    search = request.args.get("q", "")
    query = PlacementDrive.query
    if f == "pending":
        query = query.filter_by(status="pending")
    elif f == "approved":
        query = query.filter_by(status="approved")
    elif f == "closed":
        query = query.filter_by(status="closed")
    if search:
        query = query.join(Company).filter(
            (PlacementDrive.title.contains(search)) | (Company.name.contains(search))
        )
    dr = query.all()
    res = []
    for d in dr:
        c = Company.query.get(d.company_id)
        res.append(
            {
                "p_id": d.p_id,
                "title": d.title,
                "company_name": c.name,
                "status": d.status,
                "deadline": format_dt(d.deadline),
                "closed_by_admin": d.closed_by_admin,
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>/approve", methods=["PUT"])
@jwt_required()
def admin_approve_drive(drive_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    d = PlacementDrive.query.get_or_404(drive_id)
    if not d.company.approved:
        return jsonify(msg="Company not yet approved"), 400
    d.status = "approved"
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{d.company.user_id}")
    return jsonify(msg="Drive approved")


@app.route("/api/admin/drives/<int:drive_id>/close", methods=["PUT"])
@jwt_required()
def admin_close_drive(drive_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    d = PlacementDrive.query.get_or_404(drive_id)
    d.status = "closed"
    d.closed_by_admin = True
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{d.company.user_id}")
    return jsonify(msg="Drive closed")


# admin student related data view
@app.route("/api/admin/students")
@jwt_required()
@cache.cached(timeout=60, key_prefix=lambda: f"admin_students_{request.url}")
def admin_list_students():
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    f = request.args.get("filter", "all")
    search = request.args.get("q", "")
    query = Student.query
    if f == "active":
        query = query.join(User).filter(
            User.is_active == True, User.is_blacklisted == False
        )
    elif f == "inactive":
        query = query.join(User).filter(
            User.is_active == False, User.is_blacklisted == False
        )
    elif f == "blacklisted":
        query = query.join(User).filter(User.is_blacklisted == True)
    if search:
        query = query.filter(
            (Student.name.contains(search)) | (Student.roll_number.contains(search))
        )
    st = query.all()
    res = []
    for s in st:
        user = User.query.get(s.user_id)
        res.append(
            {
                "s_id": s.s_id,
                "name": s.name,
                "roll_number": s.roll_number,
                "email": user.email,
                "active": user.is_active,
                "blacklisted": user.is_blacklisted,
            }
        )
    return jsonify(res)


@app.route("/api/admin/students/<int:student_id>")
@jwt_required()
def admin_view_student(student_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    s = Student.query.get_or_404(student_id)
    u = User.query.get(s.user_id)
    return jsonify(
        s_id=s.s_id,
        name=s.name,
        roll_number=s.roll_number,
        email=u.email,
        branch=s.branch,
        cgpa=s.cgpa,
        year=s.year,
        skills=s.skills,
        resume_path=s.resume_path,
        active=u.is_active,
        blacklisted=u.is_blacklisted,
    )


@app.route("/api/admin/students/<int:student_id>/applications")
@jwt_required()
def admin_view_student_applications(student_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    apps = Application.query.filter_by(student_id=student_id).all()
    res = []
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        res.append(
            {
                "a_id": a.a_id,
                "company_name": c.name,
                "drive_title": d.title,
                "status": a.status,
                "applied_date": format_dt(a.applied_date),
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>")
@jwt_required()
def admin_view_drive(drive_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    d = PlacementDrive.query.get_or_404(drive_id)
    c = Company.query.get(d.company_id)
    return jsonify(
        p_id=d.p_id,
        title=d.title,
        description=d.description,
        branch=d.branch,
        cgpa_min=d.cgpa_min,
        year=d.year,
        deadline=format_dt(d.deadline),
        status=d.status,
        company_name=c.name,
        company_id=c.c_id,
        required_skills=d.required_skills,
        preferred_skills=d.preferred_skills,
        technologies=d.technologies,
        experience=d.experience,
        closed_by_admin=d.closed_by_admin,
    )


@app.route("/api/admin/students/<int:student_id>/toggle-active", methods=["PUT"])
@jwt_required()
def admin_toggle_student_active(student_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    s = Student.query.get_or_404(student_id)
    u = User.query.get(s.user_id)
    u.is_active = not u.is_active
    db.session.commit()
    invalidate_admin_caches()
    return jsonify(msg=f"Student {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/admin/students/<int:student_id>/toggle-blacklist", methods=["PUT"])
@jwt_required()
def admin_toggle_student_blacklist(student_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    s = Student.query.get_or_404(student_id)
    u = User.query.get(s.user_id)
    u.is_blacklisted = not u.is_blacklisted
    db.session.commit()
    invalidate_admin_caches()
    return jsonify(
        msg=f"Student {'Blacklisted' if u.is_blacklisted else 'Unblacklisted'}"
    )


@app.route("/api/admin/students/<int:student_id>", methods=["DELETE"])
@jwt_required()
def admin_delete_student(student_id):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    s = Student.query.get_or_404(student_id)
    user = User.query.get(s.user_id)
    db.session.delete(s)
    if user:
        db.session.delete(user)
    db.session.commit()
    invalidate_admin_caches()
    return jsonify(msg="Student deleted")


# admin portal charts view
@app.route("/api/admin/chart-data")
@jwt_required()
@cache.cached(timeout=120, key_prefix="admin_chart_data")
def admin_chart_data():
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check

    applied = Application.query.count()
    shortlisted = Application.query.filter_by(status="shortlisted").count()
    selected = Application.query.filter_by(status="selected").count()
    rejected = Application.query.filter_by(status="rejected").count()

    companies = Company.query.filter_by(approved=True).all()
    company_drive_counts = []
    for c in companies:
        count = PlacementDrive.query.filter_by(company_id=c.c_id).count()
        company_drive_counts.append({"company": c.name, "drives": count})

    monthly_data = (
        db.session.query(
            func.strftime("%Y-%m", Application.applied_date).label("month"),
            func.count().label("cnt"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_labels = [row.month for row in monthly_data]
    monthly_counts = [row.cnt for row in monthly_data]

    drives = PlacementDrive.query.filter(
        PlacementDrive.status.in_(["approved", "closed"])
    ).all()
    skill_freq = {}
    for d in drives:
        skills_list = split_skills(d.required_skills) + split_skills(d.technologies)
        for skill in skills_list:
            if skill:
                skill_freq[skill.lower()] = skill_freq.get(skill.lower(), 0) + 1
    top_skills = sorted(skill_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    skill_labels = [s[0] for s in top_skills]
    skill_values = [s[1] for s in top_skills]

    return jsonify(
        funnel={
            "applied": applied,
            "shortlisted": shortlisted,
            "selected": selected,
            "rejected": rejected,
        },
        company_drives=company_drive_counts,
        monthly_applications={"labels": monthly_labels, "data": monthly_counts},
        skill_demand={"labels": skill_labels, "data": skill_values},
    )


# admin portal data downloads route
@app.route("/api/admin/report/<report_type>")
@jwt_required()
def admin_report(report_type):
    err = check_role("admin")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    output = StringIO()
    writer = csv.writer(output)

    if report_type == "placements":
        writer.writerow(["Student ID", "Name", "Company", "Role", "Package", "Date"])
        apps = Application.query.filter_by(status="selected").all()
        for a in apps:
            s = Student.query.get(a.student_id)
            d = PlacementDrive.query.get(a.drive_id)
            c = Company.query.get(d.company_id)
            writer.writerow(
                [
                    s.s_id,
                    s.name,
                    c.name,
                    d.title,
                    a.package or "N/A",
                    format_dt(a.placement_date),
                ]
            )

    elif report_type == "companies":
        writer.writerow(
            ["Company ID", "Name", "Industry", "Location", "Approved", "Active"]
        )
        companies = Company.query.all()
        for c in companies:
            u = User.query.get(c.user_id)
            writer.writerow(
                [c.c_id, c.name, c.industry, c.location, c.approved, u.is_active]
            )

    elif report_type == "drives":
        writer.writerow(
            ["Drive ID", "Title", "Company", "Status", "Deadline", "Required Skills"]
        )
        drives = PlacementDrive.query.all()
        for d in drives:
            c = Company.query.get(d.company_id)
            writer.writerow(
                [
                    d.p_id,
                    d.title,
                    c.name,
                    d.status,
                    format_dt(d.deadline),
                    d.required_skills,
                ]
            )

    elif report_type == "applications":
        writer.writerow(
            ["Application ID", "Student", "Drive", "Company", "Status", "Date"]
        )
        apps = Application.query.all()
        for a in apps:
            s = Student.query.get(a.student_id)
            d = PlacementDrive.query.get(a.drive_id)
            c = Company.query.get(d.company_id)
            writer.writerow(
                [a.a_id, s.name, d.title, c.name, a.status, format_dt(a.applied_date)]
            )

    elif report_type == "stats":
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Students", Student.query.count()])
        writer.writerow(["Total Companies", Company.query.count()])
        writer.writerow(["Total Drives", PlacementDrive.query.count()])
        writer.writerow(["Total Applications", Application.query.count()])
        writer.writerow(
            ["Selected", Application.query.filter_by(status="selected").count()]
        )

    csv_content = output.getvalue()
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename={report_type}_report.csv"
        },
    )


# company dashboard view
@app.route("/api/company/dashboard")
@jwt_required()
def company_dashboard():
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    cache_key = f"company_dashboard_{u_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    c = Company.query.filter_by(user_id=u_id).first_or_404()
    all_d = PlacementDrive.query.filter_by(company_id=c.c_id).all()
    active_drives = []
    closed_drives = []
    for d in all_d:
        ac = Application.query.filter_by(drive_id=d.p_id).count()
        dd = {
            "p_id": d.p_id,
            "title": d.title,
            "description": d.description,
            "branch": d.branch,
            "cgpa_min": d.cgpa_min,
            "year": d.year,
            "deadline": format_dt(d.deadline),
            "status": d.status,
            "applicants": ac,
            "required_skills": d.required_skills,
            "preferred_skills": d.preferred_skills,
            "technologies": d.technologies,
            "experience": d.experience,
            "closed_by_admin": d.closed_by_admin,
        }
        if d.status == "closed":
            closed_drives.append(dd)
        else:
            active_drives.append(dd)
    resp = jsonify(
        company_name=c.name,
        approved=c.approved,
        is_active=c.user.is_active,
        active_drives=active_drives,
        closed_drives=closed_drives,
    )
    cache.set(cache_key, resp, timeout=60)
    return resp


@app.route("/api/company/profile", methods=["GET", "PUT"])
@jwt_required()
def company_profile():
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    if request.method == "GET":
        return jsonify(
            name=c.name,
            industry=c.industry,
            location=c.location,
            description=c.description,
            website=c.website,
            hr_contact=c.hr_contact,
        )
    d = request.get_json()
    c.name = d.get("name", c.name).strip()
    c.industry = d.get("industry", c.industry)
    c.location = d.get("location", c.location)
    c.description = d.get("description", c.description)
    c.website = d.get("website", c.website)
    c.hr_contact = d.get("hr_contact", c.hr_contact)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Profile updated")


# company drive creation routes
@app.route("/api/company/drives", methods=["POST"])
@jwt_required()
def company_create_drive():
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    if not c.approved:
        return jsonify(msg="Company not approved"), 403
    if not c.user.is_active or c.user.is_blacklisted:
        return jsonify(msg="Your account is deactivated."), 403
    d = request.get_json()
    if not d.get("title"):
        return jsonify(msg="Job title is required"), 400
    deadline_str = d.get("deadline")
    deadline = None
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str)
        except:
            return jsonify(msg="Invalid deadline format"), 400
    branch = d.get("branch", "").strip() or None
    cgpa_min = d.get("cgpa_min")
    if cgpa_min is not None:
        try:
            cgpa_min = float(cgpa_min)
            if cgpa_min < 0 or cgpa_min > 10:
                return jsonify(msg="CGPA min must be between 0 and 10"), 400
        except:
            return jsonify(msg="Invalid CGPA min"), 400
    year = d.get("year", "").strip() or None
    dr = PlacementDrive(
        company_id=c.c_id,
        title=d["title"].strip(),
        description=d.get("description", "").strip() or None,
        branch=branch,
        cgpa_min=cgpa_min,
        year=year,
        deadline=deadline,
        status="pending",
        required_skills=d.get("required_skills", "").strip() or None,
        preferred_skills=d.get("preferred_skills", "").strip() or None,
        technologies=d.get("technologies", "").strip() or None,
        experience=d.get("experience", "").strip() or None,
    )
    db.session.add(dr)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Drive Created. Pending Approval"), 201


@app.route("/api/company/drives/<int:drive_id>", methods=["PUT"])
@jwt_required()
def company_update_drive(drive_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    req = request.get_json()
    d.title = req.get("title", d.title).strip()
    d.description = req.get("description", d.description)
    d.branch = req.get("branch", d.branch)
    cgpa_min = req.get("cgpa_min")
    if cgpa_min is not None:
        try:
            cgpa_min = float(cgpa_min)
            if cgpa_min < 0 or cgpa_min > 10:
                return jsonify(msg="CGPA min must be between 0 and 10"), 400
            d.cgpa_min = cgpa_min
        except:
            return jsonify(msg="Invalid CGPA min"), 400
    d.year = req.get("year", d.year)
    deadline_str = req.get("deadline")
    if deadline_str is not None:
        try:
            d.deadline = datetime.fromisoformat(deadline_str) if deadline_str else None
        except:
            return jsonify(msg="Invalid deadline format"), 400
    d.required_skills = req.get("required_skills", d.required_skills)
    d.preferred_skills = req.get("preferred_skills", d.preferred_skills)
    d.technologies = req.get("technologies", d.technologies)
    d.experience = req.get("experience", d.experience)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Drive updated")


@app.route("/api/company/drives/<int:drive_id>", methods=["DELETE"])
@jwt_required()
def company_delete_drive(drive_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    db.session.delete(d)
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Drive deleted")


@app.route("/api/company/drives/<int:drive_id>/toggle-status", methods=["PUT"])
@jwt_required()
def company_toggle_drive_status(drive_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    if d.status == "approved":
        d.status = "closed"
        d.closed_by_admin = False
    elif d.status == "closed":
        if d.closed_by_admin:
            return jsonify(msg="Drive was closed by Admin and cannot be reopened."), 403
        d.status = "approved"
        d.closed_by_admin = False
    else:
        return jsonify(msg="Drive status cannot be toggled"), 400
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg=f"Drive status changed to {d.status}")


@app.route("/api/company/drives/<int:drive_id>/applications")
@jwt_required()
def company_view_applications(drive_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    app = Application.query.filter_by(drive_id=drive_id).all()
    res = []
    for a in app:
        s = Student.query.get(a.student_id)
        job_skills = set()
        for field in [
            d.required_skills,
            d.preferred_skills,
            d.technologies,
            d.title,
            d.description,
        ]:
            if field:
                job_skills.update(split_skills(field))
        student_skills = set(split_skills(s.skills))
        matched = list(student_skills & job_skills)
        missing = list(job_skills - student_skills)
        score = int((len(matched) / len(job_skills)) * 100) if job_skills else 0
        score = min(score, 100)
        explanation = (
            f"Match based on {len(matched)} out of {len(job_skills)} required skills."
        )
        res.append(
            {
                "a_id": a.a_id,
                "student_id": s.s_id,
                "student_name": s.name,
                "roll_number": s.roll_number,
                "branch": s.branch,
                "cgpa": s.cgpa,
                "status": a.status,
                "applied_date": format_dt(a.applied_date),
                "resume_url": f"/api/student/resume/{s.s_id}"
                if s.resume_path
                else None,
                "ats_score": score,
                "ats_matched_skills": matched,
                "ats_missing_skills": missing,
                "ats_match_percentage": score,
                "ats_explanation": explanation,
            }
        )
    return jsonify(res)


@app.route("/api/company/applications/<int:app_id>", methods=["PUT"])
@jwt_required()
def company_update_application(app_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    app = Application.query.get_or_404(app_id)
    dr = PlacementDrive.query.get(app.drive_id)
    if dr.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    d = request.get_json()
    stat = d.get("status")
    if stat not in ["shortlisted", "selected", "rejected"]:
        return jsonify(msg="Invalid status"), 400
    old_status = app.status
    app.status = stat
    if stat == "selected":
        app.placement_date = datetime.now()
    package = d.get("package")
    if package is not None:
        app.package = package
    db.session.commit()
    if old_status != stat:
        send_application_status_email.delay(app.student_id, app.drive_id, stat)
    s = Student.query.get(app.student_id)
    cache.delete(f"student_dashboard_{s.user_id}")
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Status updated")


@app.route("/api/company/ratings")
@jwt_required()
def company_ratings():
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    ratings = compute_company_ratings(c.c_id)
    return jsonify(ratings)


@app.route("/api/company/reviews")
@jwt_required()
def company_reviews():
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    reviews = Review.query.filter_by(company_id=c.c_id).all()
    res = []
    for rv in reviews:
        sub = {}
        if rv.sub_ratings:
            try:
                sub = json.loads(rv.sub_ratings)
            except:
                pass
        res.append(
            {
                "r_id": rv.r_id,
                "review_type": rv.review_type,
                "sub_ratings": sub,
                "comment": rv.comment,
                "date": format_dt(rv.created_at),
            }
        )
    return jsonify(res)


@app.route("/api/company/student/<int:student_id>")
@jwt_required()
def company_view_student_profile(student_id):
    err = check_role("company")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    s = Student.query.get_or_404(student_id)
    u = User.query.get(s.user_id)
    return jsonify(
        s_id=s.s_id,
        name=s.name,
        email=u.email,
        roll_number=s.roll_number,
        branch=s.branch,
        cgpa=s.cgpa,
        year=s.year,
        skills=s.skills,
        resume_path=s.resume_path,
    )


# student dashboard view
@app.route("/api/student/dashboard")
@jwt_required()
def student_dashboard():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    cache_key = f"student_dashboard_{u_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    s = Student.query.filter_by(user_id=u_id).first_or_404()

    ad = PlacementDrive.query.filter_by(status="approved").all()
    dl = []
    for d in ad:
        e = True
        if d.branch and s.branch:
            branches = [b.strip() for b in d.branch.split(",")]
            if s.branch not in branches:
                e = False
        if d.cgpa_min is not None and s.cgpa is not None and s.cgpa < d.cgpa_min:
            e = False
        if d.year and s.year:
            years = [y.strip() for y in d.year.split(",")]
            if str(s.year) not in years:
                e = False

        if not e:
            continue

        a = Application.query.filter_by(student_id=s.s_id, drive_id=d.p_id).first()
        c = Company.query.get(d.company_id)
        r = compute_company_ratings(c.c_id)

        dl.append(
            {
                "p_id": d.p_id,
                "title": d.title,
                "company_name": c.name,
                "description": d.description,
                "branch": d.branch,
                "cgpa_min": d.cgpa_min,
                "year": d.year,
                "deadline": format_dt(d.deadline),
                "applied": a is not None,
                "status": a.status if a else None,
                "company_id": c.c_id,
                "company_ratings": r,
                "required_skills": d.required_skills,
                "preferred_skills": d.preferred_skills,
                "technologies": d.technologies,
                "experience": d.experience,
            }
        )

    available_drives = len(dl)
    applied_count = Application.query.filter_by(student_id=s.s_id).count()
    shortlisted_count = Application.query.filter_by(
        student_id=s.s_id, status="shortlisted"
    ).count()
    selected_count = Application.query.filter_by(
        student_id=s.s_id, status="selected"
    ).count()
    rejected_count = Application.query.filter_by(
        student_id=s.s_id, status="rejected"
    ).count()

    resp = jsonify(
        student_name=s.name,
        is_active=s.user.is_active,
        drives=dl,
        stats={
            "available": available_drives,
            "applied": applied_count,
            "shortlisted": shortlisted_count,
            "selected": selected_count,
            "rejected": rejected_count,
        },
    )
    cache.set(cache_key, resp, timeout=30)
    return resp


# student application for drive route
@app.route("/api/student/apply/<int:drive_id>", methods=["POST"])
@jwt_required()
def student_apply(drive_id):
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)

    if d.status != "approved":
        return jsonify(msg="Drive not open for applications"), 400
    if not s.user.is_active or s.user.is_blacklisted:
        return jsonify(msg="Your account is deactivated. You cannot apply."), 403

    if d.branch and s.branch:
        br = [b.strip() for b in d.branch.split(",")]
        if s.branch not in br:
            return jsonify(msg="Not e (branch)"), 403
    if d.cgpa_min is not None and s.cgpa is not None and s.cgpa < d.cgpa_min:
        return jsonify(msg="Not Eligible due to CGPA"), 403
    if d.year and s.year:
        yr = [y.strip() for y in d.year.split(",")]
        if str(s.year) not in yr:
            return jsonify(msg="Not Eligible due to year"), 403

    exist = Application.query.filter_by(student_id=s.s_id, drive_id=drive_id).first()
    if exist:
        return jsonify(msg="Already Applied"), 400

    app = Application(student_id=s.s_id, drive_id=drive_id, status="applied")
    db.session.add(app)
    db.session.commit()
    cache.delete(f"student_dashboard_{u_id}")
    return jsonify(msg="Applied successfully")


@app.route("/api/student/applications")
@jwt_required()
def student_applications():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()
    res = []
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        review = Review.query.filter_by(
            student_id=s.s_id, company_id=c.c_id, drive_id=d.p_id
        ).first()
        res.append(
            {
                "a_id": a.a_id,
                "drive_title": d.title,
                "company_name": c.name,
                "status": a.status,
                "applied_date": format_dt(a.applied_date),
                "company_id": c.c_id,
                "drive_id": d.p_id,
                "has_review": review is not None,
                "review_type": review.review_type if review else None,
            }
        )
    return jsonify(res)


@app.route("/api/student/profile", methods=["GET", "PUT"])
@jwt_required()
def student_profile():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    if request.method == "GET":
        return jsonify(
            name=s.name,
            roll_number=s.roll_number,
            branch=s.branch,
            cgpa=s.cgpa,
            year=s.year,
            skills=s.skills,
            resume_path=s.resume_path,
        )
    else:
        d = request.form if request.form else request.get_json()
        if "name" in d:
            s.name = d["name"].strip()
        if "roll_number" in d:
            s.roll_number = d["roll_number"].strip() or None
        if "branch" in d:
            s.branch = d["branch"].strip() or None
        if "cgpa" in d:
            try:
                cgpa = float(d["cgpa"])
                if cgpa < 0 or cgpa > 10:
                    return jsonify(msg="CGPA must be between 0 and 10"), 400
                s.cgpa = cgpa
            except:
                return jsonify(msg="Invalid CGPA"), 400
        if "year" in d:
            try:
                s.year = int(d["year"])
            except:
                return jsonify(msg="Invalid year"), 400
        if "skills" in d:
            s.skills = d["skills"].strip() or None
        if "resume" in request.files:
            file = request.files["resume"]
            if file.filename != "":
                filename = secure_filename(f"{u_id}_{file.filename}")
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(file_path)
                s.resume_path = filename
        db.session.commit()
        cache.delete(f"student_dashboard_{u_id}")
        return jsonify(msg="Profile Updated")


@app.route("/api/student/upload-resume", methods=["POST"])
@jwt_required()
def student_upload_resume():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    if "resume" not in request.files:
        return jsonify(msg="No file"), 400
    file = request.files["resume"]
    if file.filename == "":
        return jsonify(msg="No file selected"), 400
    filename = secure_filename(f"{u_id}_{file.filename}")
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    s.resume_path = filename
    db.session.commit()
    return jsonify(msg="Resume uploaded")


@app.route("/api/student/resume/<int:student_id>")
@jwt_required(locations=["headers", "query_string"])
def serve_resume(student_id):
    u_id = get_jwt_identity()
    user = User.query.get(u_id)
    s = Student.query.get_or_404(student_id)
    if user.role not in ["company", "admin"] and u_id != s.user_id:
        return jsonify(msg="Unauthorized"), 403
    if not s.resume_path:
        return jsonify(msg="No resume uploaded"), 404
    return send_from_directory(app.config["UPLOAD_FOLDER"], s.resume_path)


@app.route("/api/student/history")
@jwt_required()
def student_history():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()
    h = []
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        company_review = Review.query.filter_by(
            student_id=s.s_id, company_id=c.c_id, review_type="company"
        ).first()
        interview_review = Review.query.filter_by(
            student_id=s.s_id, company_id=c.c_id, review_type="interview"
        ).first()
        company_rev_data = None
        if company_review:
            sub = {}
            try:
                sub = json.loads(company_review.sub_ratings)
            except:
                pass
            company_rev_data = {
                "r_id": company_review.r_id,
                "sub_ratings": sub,
                "comment": company_review.comment,
            }
        interview_rev_data = None
        if interview_review:
            sub = {}
            try:
                sub = json.loads(interview_review.sub_ratings)
            except:
                pass
            interview_rev_data = {
                "r_id": interview_review.r_id,
                "sub_ratings": sub,
                "comment": interview_review.comment,
            }
        h.append(
            {
                "company_name": c.name,
                "position": d.title,
                "status": a.status,
                "package": a.package or "N/A",
                "placement_date": format_dt(a.placement_date)
                if a.placement_date
                else "N/A",
                "applied_date": format_dt(a.applied_date),
                "company_id": c.c_id,
                "drive_id": d.p_id,
                "company_review": company_rev_data,
                "interview_review": interview_rev_data,
            }
        )
    return jsonify(h)


@app.route("/api/student/export-csv", methods=["POST"])
@jwt_required()
def student_export_csv():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    t = export_student_csv_task.delay(s.s_id)
    return jsonify(msg="CSV Exported. You will receive an email shortly.", task_id=t.id)


@app.route("/api/student/export-csv-download", methods=["GET"])
@jwt_required()
def student_export_csv_download():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()

    l = ["Student ID,Company,Drive Title,Status,Date"]
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        l.append(f"{s.s_id},{c.name},{d.title},{a.status},{format_dt(a.applied_date)}")
    csv_content = "\n".join(l)

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=applications_{s.s_id}.csv"
        },
    )


@app.route("/api/student/ats-check", methods=["POST"])
@jwt_required()
def ats_check():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    data = request.get_json()
    drive_id = data.get("drive_id")
    if not drive_id:
        return jsonify(msg="Drive ID required"), 400
    d = PlacementDrive.query.get_or_404(drive_id)

    job_skills = set()
    for field in [
        d.required_skills,
        d.preferred_skills,
        d.technologies,
        d.title,
        d.description,
    ]:
        if field:
            job_skills.update(split_skills(field))

    student_skills = set(split_skills(s.skills))
    matched = list(student_skills & job_skills)
    score = int((len(matched) / len(job_skills)) * 100) if job_skills else 0
    return jsonify(
        score=min(score, 100), matched_skills=matched, total_skills=len(job_skills)
    )


@app.route("/api/student/review", methods=["POST"])
@jwt_required()
def submit_review():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    d = request.get_json()
    company_id = d.get("company_id")
    drive_id = d.get("drive_id")
    review_type = d.get("review_type")
    sub_ratings = d.get("sub_ratings")
    comment = d.get("comment", "")
    if not company_id or not review_type or not sub_ratings:
        return jsonify(msg="Missing fields"), 400
    existing = Review.query.filter_by(
        student_id=s.s_id, company_id=company_id, review_type=review_type
    ).first()
    if existing:
        existing.sub_ratings = json.dumps(sub_ratings)
        existing.comment = comment
        existing.drive_id = drive_id
        db.session.commit()
        return jsonify(msg="Review updated")
    rev = Review(
        student_id=s.s_id,
        company_id=company_id,
        drive_id=drive_id,
        review_type=review_type,
        sub_ratings=json.dumps(sub_ratings),
        comment=comment,
    )
    db.session.add(rev)
    db.session.commit()
    return jsonify(msg="Review submitted")


@app.route("/api/student/reviews", methods=["GET"])
@jwt_required()
def my_reviews():
    err = check_role("student")
    if err:
        return err
    status_check = check_user_status()
    if status_check:
        return status_check
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    revs = Review.query.filter_by(student_id=s.s_id).all()
    res = []
    for r in revs:
        c = Company.query.get(r.company_id)
        sub = {}
        if r.sub_ratings:
            try:
                sub = json.loads(r.sub_ratings)
            except:
                pass
        res.append(
            {
                "r_id": r.r_id,
                "company_name": c.name,
                "review_type": r.review_type,
                "sub_ratings": sub,
                "comment": r.comment,
                "date": format_dt(r.created_at),
            }
        )
    return jsonify(res)


@app.route("/api/public/stats")
@cache.cached(timeout=60, key_prefix="public_stats")
def public_stats():
    total_students = Student.query.count()
    total_companies = Company.query.filter_by(approved=True).count()
    total_drives = PlacementDrive.query.count()
    total_selected = Application.query.filter_by(status="selected").count()
    monthly_data = (
        db.session.query(
            func.strftime("%Y-%m", Application.applied_date).label("month"),
            func.count().label("cnt"),
        )
        .filter(Application.status == "selected")
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_labels = [row.month for row in monthly_data]
    monthly_counts = [row.cnt for row in monthly_data]
    return jsonify(
        total_students=total_students,
        total_companies=total_companies,
        total_drives=total_drives,
        total_selected=total_selected,
        monthly_selected={"labels": monthly_labels, "data": monthly_counts},
    )


@app.route("/api/company/public/<int:company_id>")
def public_company_profile(company_id):
    c = Company.query.get_or_404(company_id)
    ratings = compute_company_ratings(c.c_id)
    return jsonify(
        name=c.name,
        industry=c.industry,
        location=c.location,
        description=c.description,
        website=c.website,
        ratings=ratings,
    )


@app.route("/manifest.json")
def manifest():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 192 192'>
  <circle cx='96' cy='96' r='90' fill='#54B39A'/>
  <g transform='translate(48,44) scale(5.5)'>
    <svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='white' class='bi bi-mortarboard-fill' viewBox='0 0 16 16'>
      <path d='M8.211 2.047a.5.5 0 0 0-.422 0l-7.5 3.5a.5.5 0 0 0 .025.917l7.5 3a.5.5 0 0 0 .372 0L14 7.14V13a1 1 0 0 0-1 1v2h3v-2a1 1 0 0 0-1-1V6.739l.686-.275a.5.5 0 0 0 .025-.917z'/>
      <path d='M4.176 9.032a.5.5 0 0 0-.656.327l-.5 1.7a.5.5 0 0 0 .294.605l4.5 1.8a.5.5 0 0 0 .372 0l4.5-1.8a.5.5 0 0 0 .294-.605l-.5-1.7a.5.5 0 0 0-.656-.327L8 10.466z'/>
    </svg>
  </g>
</svg>"""

    icon = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode(
        "utf-8"
    )

    return jsonify(
        {
            "name": "Placement Portal",
            "short_name": "PPA",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#54B39A",
            "icons": [
                {"src": icon, "sizes": "192x192", "type": "image/svg+xml"},
                {
                    "src": icon,
                    "sizes": "512x512",
                    "type": "image/svg+xml",
                },
            ],
        }
    )


@app.route("/sw.js")
def service_worker():
    response = Response(
        """
const CACHE_NAME = 'placement-portal-v2';
const urlsToCache = [
    '/',
    '/templates/index.html'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(urlsToCache))
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => response || fetch(event.request))
    );
});
    """,
        mimetype="application/javascript",
    )
    return response


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
