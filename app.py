from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
from bson import ObjectId
from flask_mail import Mail, Message

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'rA04CTdatnkcazOM')

# Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# Initialize Flask-Mail
mail = Mail(app)

def send_email(subject, recipient, template):
    try:
        msg = Message(
            subject,
            recipients=[recipient],
            html=template
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

# MongoDB setup
client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
db = client['Exsel-project']

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data

    def get_id(self):
        return str(self.user_data['_id'])

@login_manager.user_loader
def load_user(user_id):
    user_data = db.users.find_one({'_id': ObjectId(user_id)})
    return User(user_data) if user_data else None

# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        
        if db.users.find_one({'email': email}):
            flash('Email already exists')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        user_data = {
            'email': email,
            'password': hashed_password,
            'role': role,
            'created_at': datetime.utcnow()
        }
        
        db.users.insert_one(user_data)
        
        # Send welcome email
        welcome_template = f"""
        <h2>Welcome to the Bus Complaint System!</h2>
        <p>Dear {email},</p>
        <p>Thank you for registering with our bus complaint management system. Your account has been successfully created.</p>
        <p>You can now log in and submit your complaints.</p>
        """
        
        if send_email('Welcome to Bus Complaint System', email, welcome_template):
            flash('Registration successful. Welcome email sent!')
        else:
            flash('Registration successful, but welcome email could not be sent.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_data = db.users.find_one({'email': email})
        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_data)
            login_user(user)
            
            if user_data['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_data['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    
    user_complaints = list(db.complaints.find({'user_id': str(current_user.user_data['_id'])}))
    return render_template('dashboard.html', complaints=user_complaints)

@app.route('/update-complaint-status/<complaint_id>/<status>')
@login_required
def update_complaint_status(complaint_id, status):
    if current_user.user_data['role'] != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('dashboard'))
    
    complaint = db.complaints.find_one_and_update(
        {'_id': ObjectId(complaint_id)},
        {'$set': {'status': status, 'updated_at': datetime.utcnow()}},
        return_document=True
    )
    
    if complaint:
        user = db.users.find_one({'_id': ObjectId(complaint['user_id'])})
        if user:
            # Send status update email
            update_template = f"""
            <h2>Complaint Status Update</h2>
            <p>Dear {user['email']},</p>
            <p>Your complaint has been updated:</p>
            <ul>
                <li>Title: {complaint['title']}</li>
                <li>New Status: {status}</li>
                <li>Updated At: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}</li>
            </ul>
            """
            
            if send_email('Complaint Status Update', user['email'], update_template):
                flash('Complaint status updated successfully. Notification email sent!')
            else:
                flash('Complaint status updated successfully, but notification email could not be sent.')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin-dashboard')
@login_required
def admin_dashboard():
    if current_user.user_data['role'] != 'admin':
        return redirect(url_for('dashboard'))
    
    complaints = list(db.complaints.find())
    users = list(db.users.find({'role': 'user'}))
    
    # Calculate statistics
    total_complaints = len(complaints)
    pending_complaints = sum(1 for c in complaints if c['status'] == 'pending')
    resolved_complaints = sum(1 for c in complaints if c['status'] == 'resolved')
    
    return render_template('admin_dashboard.html',
                          complaints=complaints,
                          users=users,
                          total_complaints=total_complaints,
                          pending_complaints=pending_complaints,
                          resolved_complaints=resolved_complaints)

@app.route('/submit-complaint', methods=['GET', 'POST'])
@login_required
def submit_complaint():
    if request.method == 'POST':
        # Enhanced form validation
        student_id = request.form.get('student_id')
        bus_route = request.form.get('bus_route')
        title = request.form.get('title')
        description = request.form.get('description')
        location = request.form.get('location')
        
        # Validate required fields
        if not all([student_id, bus_route, title, description, location]):
            flash('All fields are required')
            return redirect(url_for('submit_complaint'))
            
        complaint_data = {
            'user_id': str(current_user.user_data['_id']),
            'student_id': student_id,
            'bus_route': bus_route,
            'title': title,
            'description': description,
            'location': location,
            'status': 'pending',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = db.complaints.insert_one(complaint_data)
        
        # Send confirmation email to user
        complaint_template = f"""
        <h2>Complaint Submission Confirmation</h2>
        <p>Dear {current_user.user_data['email']},</p>
        <p>Your complaint has been successfully submitted with the following details:</p>
        <ul>
            <li>Title: {title}</li>
            <li>Bus Route: {bus_route}</li>
            <li>Location: {location}</li>
            <li>Status: Pending</li>
        </ul>
        <p>We will review your complaint and take necessary action.</p>
        """
        
        if send_email('Complaint Submission Confirmation', current_user.user_data['email'], complaint_template):
            flash('Complaint submitted successfully. Confirmation email sent!')
        else:
            flash('Complaint submitted successfully, but confirmation email could not be sent.')
        return redirect(url_for('dashboard'))
    
    # Get available bus routes (you can customize this list)
    bus_routes = ['Route 1', 'Route 2', 'Route 3', 'Route 4', 'Route 5']
    return render_template('submit_complaint.html', bus_routes=bus_routes)

if __name__ == '__main__':
    app.run(debug=True)