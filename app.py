import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery import Celery, Task
from celery.schedules import crontab
from flask import Flask, Response, jsonify, render_template, request
from flask_caching import Cache
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# conventionally, in a real world scenario in production, this is not commited to the code. it is usually added as a 'secret' and is hidden
# also, we usually have a random string for the same usually
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


class User(db.Model):
    __tablename__ = "user"
    u_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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

    applications = db.relationship("Application", backref="drive", lazy=True)


class Application(db.Model):
    __tablename__ = "application"
    a_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.s_id"), nullable=False)
    drive_id = db.Column(
        db.Integer, db.ForeignKey("placement_drive.p_id"), nullable=False
    )
    status = db.Column(db.String(20), default="applied")
    applied_date = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint("student_id", "drive_id", name="unique_application"),
    )


def sample_data():
    if User.query.filter_by(role="student").first():
        return

    s1_user = User(email="student1@portal.com", role="student")
    s1_user.set_password("pass123")
    db.session.add(s1_user)
    db.session.flush()
    s1 = Student(
        user_id=s1_user.u_id,
        name="Student 1",
        roll_number="10001",
        branch="CS",
        cgpa=8.5,
        year=2024,
        skills="Python, Flask",
    )
    db.session.add(s1)

    s2_user = User(email="student2@portal.com", role="student")
    s2_user.set_password("pass123")
    db.session.add(s2_user)
    db.session.flush()
    s2 = Student(
        user_id=s2_user.u_id,
        name="Student 2",
        roll_number="10002",
        branch="EE",
        cgpa=7.8,
        year=2024,
        skills="C++, MATLAB",
    )
    db.session.add(s2)

    c1_user = User(email="hr1@portal.com", role="company")
    c1_user.set_password("pass123")
    db.session.add(c1_user)
    db.session.flush()
    c1 = Company(
        user_id=c1_user.u_id,
        name="Company 1",
        industry="IT",
        location="Bangalore",
        approved=True,
    )
    db.session.add(c1)

    c2_user = User(email="hr2@portal.com", role="company")
    c2_user.set_password("pass123")
    db.session.add(c2_user)
    db.session.flush()
    c2 = Company(
        user_id=c2_user.u_id,
        name="Company 2",
        industry="Analytics",
        location="Mumbai",
        approved=False,
    )
    db.session.add(c2)

    db.session.flush()

    d1 = PlacementDrive(
        company_id=c1.c_id,
        title="Software Engineer",
        description="Develop web apps",
        branch="CS",
        cgpa_min=7.0,
        year="2024",
        deadline=datetime.now() + timedelta(days=30),
        status="approved",
    )
    d2 = PlacementDrive(
        company_id=c1.c_id,
        title="req Analyst",
        description="Analyze req",
        branch="CS,EE",
        cgpa_min=7.5,
        year="2024",
        deadline=datetime.now() + timedelta(days=15),
        status="pending",
    )
    db.session.add(d1)
    db.session.add(d2)

    db.session.commit()


with app.app_context():
    db.create_all()
    if not User.query.filter_by(role="admin").first():
        admin_user = User(email=app.config["ADMIN_EMAIL"], role="admin")
        admin_user.set_password(app.config["ADMIN_PASSWORD"])
        db.session.add(admin_user)
        db.session.commit()
        print("Default admin credentials: admin@portal.com | admin123")

    sample_data()


def check_role(role):
    j = get_jwt()
    if j.get("role") != role:
        return jsonify(msg="Access Forbidden for Role"), 403
    else:
        return None


def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)


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
        l.append(f"{s.s_id},{c.name},{d.title},{a.status},{a.applied_date.isoformat()}")
    csv_content = "\n".join(l)
    send_email(
        s.user.email,
        "Your Application History CSV",
        "Please find attached your placement application history.",
        attachment=("applications.csv", csv_content, "text/csv"),
    )
    return f"CSV sent to {s.user.email}"


def invalidate_admin_caches():
    cache.delete("admin_dashboard")
    cache.delete("admin_companies")
    cache.delete("admin_drives")
    cache.delete("admin_students")


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
    if not d.get("email") or not d.get("password"):
        return jsonify(msg="Email and password required"), 400
    u = User.query.filter_by(email=d.get("email")).first()
    if not u or not u.check_password(d.get("password")):
        return jsonify(msg="Invalid Email or Password"), 401
    if not u.is_active:
        return jsonify(msg="Account is Deactivated"), 403

    r = {"role": u.role}
    a = create_access_token(identity=str(u.u_id), additional_claims=r)
    return jsonify(access_token=a, role=u.role)


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


@app.route("/api/admin/dashboard")
@jwt_required()
@cache.cached(timeout=60, key_prefix="admin_dashboard")
def admin_dashboard():
    err = check_role("admin")
    if err:
        return err

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


@app.route("/api/admin/companies")
@jwt_required()
@cache.cached(timeout=60, key_prefix="admin_companies")
def admin_list_companies():
    err = check_role("admin")
    if err:
        return err

    f = request.args.get("filter", "all")
    query = Company.query
    if f == "approved":
        query = query.filter_by(approved=True)
    elif f == "unapproved":
        query = query.filter_by(approved=False)
    elif f == "active":
        query = query.join(User).filter(User.is_active == True)
    elif f == "inactive":
        query = query.join(User).filter(User.is_active == False)

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
    c = Company.query.get_or_404(company_id)
    u = User.query.get(c.user_id)
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
    )


@app.route("/api/admin/companies/<int:company_id>/drives")
@jwt_required()
def admin_view_company_drives(company_id):
    err = check_role("admin")
    if err:
        return err
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
                "deadline": d.deadline.isoformat() if d.deadline else None,
                "status": d.status,
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>/applications")
@jwt_required()
def admin_view_drive_applications(drive_id):
    err = check_role("admin")
    if err:
        return err
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
                "applied_date": a.applied_date.isoformat(),
            }
        )
    return jsonify(res)


@app.route("/api/admin/companies/<int:company_id>/approve", methods=["PUT"])
@jwt_required()
def admin_approve_company(company_id):
    err = check_role("admin")
    if err:
        return err

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

    c = Company.query.get_or_404(company_id)
    u = User.query.get(c.user_id)
    u.is_active = not u.is_active
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{c.user_id}")
    return jsonify(msg=f"Company {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/admin/drives")
@jwt_required()
@cache.cached(timeout=60, key_prefix="admin_drives")
def admin_list_drives():
    err = check_role("admin")
    if err:
        return err

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
                "deadline": d.deadline.isoformat() if d.deadline else None,
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>/approve", methods=["PUT"])
@jwt_required()
def admin_approve_drive(drive_id):
    err = check_role("admin")
    if err:
        return err

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

    d = PlacementDrive.query.get_or_404(drive_id)
    d.status = "closed"
    db.session.commit()
    invalidate_admin_caches()
    cache.delete(f"company_dashboard_{d.company.user_id}")
    return jsonify(msg="Drive closed")


@app.route("/api/admin/students")
@jwt_required()
@cache.cached(timeout=60, key_prefix="admin_students")
def admin_list_students():
    err = check_role("admin")
    if err:
        return err

    f = request.args.get("filter", "all")
    search = request.args.get("q", "")
    query = Student.query
    if f == "active":
        query = query.join(User).filter(User.is_active == True)
    elif f == "inactive":
        query = query.join(User).filter(User.is_active == False)
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
            }
        )
    return jsonify(res)


@app.route("/api/admin/students/<int:student_id>")
@jwt_required()
def admin_view_student(student_id):
    err = check_role("admin")
    if err:
        return err
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
    )


@app.route("/api/admin/students/<int:student_id>/applications")
@jwt_required()
def admin_view_student_applications(student_id):
    err = check_role("admin")
    if err:
        return err
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
                "applied_date": a.applied_date.isoformat(),
            }
        )
    return jsonify(res)


@app.route("/api/admin/drives/<int:drive_id>")
@jwt_required()
def admin_view_drive(drive_id):
    err = check_role("admin")
    if err:
        return err
    d = PlacementDrive.query.get_or_404(drive_id)
    c = Company.query.get(d.company_id)
    return jsonify(
        p_id=d.p_id,
        title=d.title,
        description=d.description,
        branch=d.branch,
        cgpa_min=d.cgpa_min,
        year=d.year,
        deadline=d.deadline.isoformat() if d.deadline else None,
        status=d.status,
        company_name=c.name,
        company_id=c.c_id,
    )


@app.route("/api/admin/students/<int:student_id>/toggle-active", methods=["PUT"])
@jwt_required()
def admin_toggle_student_active(student_id):
    err = check_role("admin")
    if err:
        return err

    s = Student.query.get_or_404(student_id)
    u = User.query.get(s.user_id)
    u.is_active = not u.is_active
    db.session.commit()
    invalidate_admin_caches()
    return jsonify(msg=f"Student {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/company/dashboard")
@jwt_required()
def company_dashboard():
    err = check_role("company")
    if err:
        return err
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
            "deadline": d.deadline.isoformat() if d.deadline else None,
            "status": d.status,
            "applicants": ac,
        }
        if d.status == "closed":
            closed_drives.append(dd)
        else:
            active_drives.append(dd)
    resp = jsonify(
        company_name=c.name,
        approved=c.approved,
        active_drives=active_drives,
        closed_drives=closed_drives,
    )
    cache.set(cache_key, resp, timeout=60)
    return resp


@app.route("/api/company/drives", methods=["POST"])
@jwt_required()
def company_create_drive():
    err = check_role("company")
    if err:
        return err
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    if not c.approved:
        return jsonify(msg="Company not approved"), 403
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
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    if d.status == "approved":
        d.status = "closed"
    elif d.status == "closed":
        d.status = "approved"
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
    u_id = get_jwt_identity()
    c = Company.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)
    if d.company_id != c.c_id:
        return jsonify(msg="Unauthorized"), 403
    app = Application.query.filter_by(drive_id=drive_id).all()
    res = []
    for a in app:
        s = Student.query.get(a.student_id)
        res.append(
            {
                "a_id": a.a_id,
                "student_id": s.s_id,
                "student_name": s.name,
                "roll_number": s.roll_number,
                "branch": s.branch,
                "cgpa": s.cgpa,
                "status": a.status,
                "applied_date": a.applied_date.isoformat(),
            }
        )
    return jsonify(res)


@app.route("/api/company/applications/<int:app_id>", methods=["PUT"])
@jwt_required()
def company_update_application(app_id):
    err = check_role("company")
    if err:
        return err
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
    app.status = stat
    db.session.commit()
    s = Student.query.get(app.student_id)
    cache.delete(f"student_dashboard_{s.user_id}")
    cache.delete(f"company_dashboard_{u_id}")
    return jsonify(msg="Status updated")


@app.route("/api/student/dashboard")
@jwt_required()
def student_dashboard():
    err = check_role("student")
    if err:
        return err
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
        dl.append(
            {
                "p_id": d.p_id,
                "title": d.title,
                "company_name": c.name,
                "description": d.description,
                "branch": d.branch,
                "cgpa_min": d.cgpa_min,
                "year": d.year,
                "deadline": d.deadline.isoformat() if d.deadline else None,
                "applied": a is not None,
                "status": a.status if a else None,
            }
        )
    resp = jsonify(student_name=s.name, drives=dl)
    cache.set(cache_key, resp, timeout=30)
    return resp


@app.route("/api/student/apply/<int:drive_id>", methods=["POST"])
@jwt_required()
def student_apply(drive_id):
    err = check_role("student")
    if err:
        return err
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    d = PlacementDrive.query.get_or_404(drive_id)

    if d.status != "approved":
        return jsonify(msg="Drive not open for applications"), 400

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
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()
    res = []
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        res.append(
            {
                "a_id": a.a_id,
                "drive_title": d.title,
                "company_name": c.name,
                "status": a.status,
                "applied_date": a.applied_date.isoformat(),
            }
        )
    return jsonify(res)


@app.route("/api/student/profile", methods=["GET", "PUT"])
@jwt_required()
def student_profile():
    err = check_role("student")
    if err:
        return err
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
        d = request.get_json()
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
        db.session.commit()
        cache.delete(f"student_dashboard_{u_id}")
        return jsonify(msg="Profile Updated")


@app.route("/api/student/history")
@jwt_required()
def student_history():
    err = check_role("student")
    if err:
        return err
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()
    h = []
    for a in apps:
        if a.status in ["selected", "rejected"]:
            d = PlacementDrive.query.get(a.drive_id)
            c = Company.query.get(d.company_id)
            h.append(
                {
                    "company_name": c.name,
                    "position": d.title,
                    "status": a.status,
                    "date": a.applied_date.isoformat(),
                }
            )
    return jsonify(h)


@app.route("/api/student/export-csv", methods=["POST"])
@jwt_required()
def student_export_csv():
    err = check_role("student")
    if err:
        return err
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
    u_id = get_jwt_identity()
    s = Student.query.filter_by(user_id=u_id).first_or_404()
    apps = Application.query.filter_by(student_id=s.s_id).all()

    l = ["Student ID,Company,Drive Title,Status,Date"]
    for a in apps:
        d = PlacementDrive.query.get(a.drive_id)
        c = Company.query.get(d.company_id)
        l.append(f"{s.s_id},{c.name},{d.title},{a.status},{a.applied_date.isoformat()}")
    csv_content = "\n".join(l)

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=applications_{s.s_id}.csv"
        },
    )


@app.route("/api/clear-cache", methods=["POST"])
@jwt_required()
def clear_all_cache():
    err = check_role("admin")
    if err:
        return err
    cache.clear()
    return jsonify(msg="All cache cleared")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
