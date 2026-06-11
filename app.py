from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request
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


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
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
    if User.query.filter_by(email=d["email"]).first():
        return jsonify(msg="Email already registered"), 400
    u = User(email=d["email"], role="student")
    u.set_password(d["password"])
    db.session.add(u)
    db.session.flush()

    s = Student(
        user_id=u.u_id,
        name=d["name"],
        roll_number=d.get("roll_number"),
        branch=d.get("branch"),
        cgpa=d.get("cgpa"),
        year=d.get("year"),
        skills=d.get("skills"),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(msg="Student Registered."), 201


@app.route("/api/register/company", methods=["POST"])
def register_company():
    d = request.get_json()
    if User.query.filter_by(email=d["email"]).first():
        return jsonify(msg="Email already registered"), 400
    u = User(email=d["email"], role="company")
    u.set_password(d["password"])
    db.session.add(u)
    db.session.flush()

    c = Company(
        user_id=u.u_id,
        name=d["name"],
        industry=d.get("industry"),
        location=d.get("location"),
        description=d.get("description"),
        website=d.get("website"),
        hr_contact=d.get("hr_contact"),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(msg="Company Registered. Approval Pending"), 201


@app.route("/api/admin/dashboard")
@jwt_required()
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
    return jsonify(msg=f"Company {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/admin/drives")
@jwt_required()
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
    return jsonify(msg="Drive closed")


@app.route("/api/admin/students")
@jwt_required()
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
    return jsonify(msg=f"Student {'Deactivated' if not u.is_active else 'Activated'}")


@app.route("/api/company/dashboard")
@jwt_required()
def company_dashboard():
    err = check_role("company")
    if err:
        return err
    u_id = get_jwt_identity()
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
    return jsonify(
        company_name=c.name,
        approved=c.approved,
        active_drives=active_drives,
        closed_drives=closed_drives,
    )


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
    deadline_str = d.get("deadline")
    deadline = datetime.fromisoformat(deadline_str) if deadline_str else None
    dr = PlacementDrive(
        company_id=c.c_id,
        title=d["title"],
        description=d.get("description"),
        branch=d.get("branch"),
        cgpa_min=d.get("cgpa_min"),
        year=d.get("year"),
        deadline=deadline,
        status="pending",
    )
    db.session.add(dr)
    db.session.commit()
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
    d.title = req.get("title", d.title)
    d.description = req.get("description", d.description)
    d.branch = req.get("branch", d.branch)
    d.cgpa_min = req.get("cgpa_min", d.cgpa_min)
    d.year = req.get("year", d.year)
    deadline_str = req.get("deadline")
    if deadline_str is not None:
        d.deadline = datetime.fromisoformat(deadline_str) if deadline_str else None
    db.session.commit()
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
    return jsonify(msg="Status updated")


@app.route("/api/student/dashboard")
@jwt_required()
def student_dashboard():
    err = check_role("student")
    if err:
        return err
    u_id = get_jwt_identity()
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
    return jsonify(student_name=s.name, drives=dl)


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
        s.name = d.get("name", s.name)
        s.roll_number = d.get("roll_number", s.roll_number)
        s.branch = d.get("branch", s.branch)
        if "cgpa" in d:
            s.cgpa = d["cgpa"]
        if "year" in d:
            s.year = d["year"]
        s.skills = d.get("skills", s.skills)
        db.session.commit()
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


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
