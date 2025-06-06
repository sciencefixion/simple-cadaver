from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import json
import boto3
import secrets
import base64
from botocore.exceptions import ClientError
import logging
from logging.handlers import RotatingFileHandler

# Initialize Flask app
app = Flask(__name__)

# ======================
# Configuration Settings
# ======================

def get_flask_secret():
    """Retrieve secret key from AWS Secrets Manager with fallback options"""
    secret_name = "prod/flask/app_secret"
    region_name = "us-east-2"

    try:
        client = boto3.client('secretsmanager', region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)
        
        if 'SecretBinary' in response:
            secret = base64.b64decode(response['SecretBinary'])
        else:
            secret = response['SecretString']
            
        return json.loads(secret)['flask_secret_key']
    except ClientError as e:
        app.logger.error(f"AWS Secrets Manager Error: {e.response['Error']['Code']}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error retrieving secret: {str(e)}")
        return None

# Set secret key with multiple fallback options
secret_key = (
    get_flask_secret() or 
    os.environ.get('FLASK_SECRET_KEY') or 
    secrets.token_hex(32)
)
app.secret_key = secret_key

if not get_flask_secret() and not os.environ.get('FLASK_SECRET_KEY'):
    app.logger.warning("Using temporary secret key - not suitable for production!")

app.config.update(
    # Security settings
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=1),
    SESSION_COOKIE_NAME='flask_app_session',  # Explicit name
    SESSION_REFRESH_EACH_REQUEST=True,
    
    # Database settings
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_POOL_RECYCLE=3600,  # Recycle connections every hour
    SQLALCHEMY_POOL_TIMEOUT=30,
    SQLALCHEMY_ENGINE_OPTIONS={
        'pool_pre_ping': True,
        'pool_size': 20,
        'max_overflow': 10,
        'connect_args': {
            'ssl': {'ca': '/etc/ssl/certs/rds-combined-ca-bundle.pem'}  # Common Linux location for RDS SSL certificate
        }
    }
)

# ======================
# Logging Configuration
# ======================

def configure_logging():
    """Configure production-grade logging"""
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)

    if not os.path.exists('logs'):
        os.makedirs('logs')

    file_handler = RotatingFileHandler(
        'logs/app.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Application starting up')

configure_logging()

# ======================
# Database Configuration
# ======================

def get_db_secret(secret_name, region_name='us-east-2'):
    """Retrieve database credentials from AWS Secrets Manager"""
    try:
        client = boto3.client('secretsmanager', region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except Exception as e:
        app.logger.error(f"Error fetching DB secret: {str(e)}")
        raise

try:
    secret = get_db_secret('prod/rds/mydb')
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{secret['username']}:{secret['password']}"
        f"@{secret['host']}/{secret['dbname']}?charset=utf8mb4"
    )
except Exception as e:
    app.logger.critical(f"Failed to configure database: {str(e)}")
    raise

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ======================
# AWS S3 Configuration
# ======================

BUCKET_NAME = 'flask-todo-april-bucket2'

def upload_file_to_s3(file_path, s3_key):
    """Upload file to S3 with proper error handling"""
    s3 = boto3.client("s3")
    try:
        s3.upload_file(
            file_path,
            BUCKET_NAME,
            s3_key,
            ExtraArgs={
                'ACL': 'private',
                'ContentType': 'application/octet-stream'
            }
        )
        app.logger.info(f"Uploaded {s3_key} to {BUCKET_NAME}")
        return f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
    except Exception as e:
        app.logger.error(f"Error uploading file {s3_key}: {str(e)}")
        raise

# ======================
# Database Models
# ======================

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    current_player = db.Column(db.Integer, default=1)
    max_players = db.Column(db.Integer, default=3)
    round = db.Column(db.Integer, default=1)
    is_complete = db.Column(db.Boolean, default=False)
    contributions = db.relationship('Contribution', backref='game', lazy=True)
    image_url = db.Column(db.String(255))

class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    player_number = db.Column(db.Integer, nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables (run once)
with app.app_context():
    db.create_all()

# ======================
# Application Routes
# ======================

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        # Create a new game
        game_code = os.urandom(4).hex().upper()
        max_players = int(request.form['player_count'])
        
        new_game = Game(
            code=game_code,
            max_players=max_players
        )
        db.session.add(new_game)
        db.session.commit()
        
        session['game_code'] = game_code
        return redirect(url_for('game'))
    
    return render_template('setup.html')

@app.route('/game', methods=['GET', 'POST'])
def game():
    if 'game_code' not in session:
        return redirect(url_for('home'))
    
    game = Game.query.filter_by(code=session['game_code']).first()
    
    if request.method == 'POST':
        # Add contribution
        contribution = request.form['contribution']
        
        new_contribution = Contribution(
            game_id=game.id,
            player_number=game.current_player,
            round_number=game.round,
            text=contribution
        )
        db.session.add(new_contribution)
        
        # Update game state
        if game.current_player < game.max_players:
            game.current_player += 1
        else:
            game.current_player = 1
            game.round += 1
        
        # Check if game is complete
        if game.round > 3:
            game.is_complete = True
        
        db.session.commit()
        
        if game.is_complete:
            return redirect(url_for('result'))
    
    # Get last contribution
    last_contribution = Contribution.query.filter_by(game_id=game.id)\
        .order_by(Contribution.id.desc()).first()
    
    show_input = game.current_player == 1 or 'show_all' in request.args
    
    return render_template('game.html',
                         last_contribution=last_contribution.text if last_contribution else "",
                         current_player=game.current_player,
                         max_players=game.max_players,
                         round=game.round,
                         show_input=show_input)

@app.route('/result')
def result():
    if 'game_code' not in session:
        return redirect(url_for('home'))
    
    game = Game.query.filter_by(code=session['game_code']).first()
    contributions = Contribution.query.filter_by(game_id=game.id)\
        .order_by(Contribution.round_number, Contribution.player_number).all()
    
    return render_template('result.html', 
                         contributions=contributions,
                         game_code=game.code,
                         image_url=game.image_url)

# For image uploads
@app.route('/upload_image/<game_code>', methods=['POST'])
def upload_image(game_code):
    game = Game.query.filter_by(code=game_code).first()
    if not game:
        return redirect(url_for('home'))
    
    if 'image' not in request.files:
        return redirect(request.url)
    
    file = request.files['image']
    if file.filename == '':
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{game_code}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        game.image_url = filename
        db.session.commit()
    
    return redirect(url_for('result'))

# To serve uploaded images
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ======================
# Application Startup
# ======================

if __name__ == '__main__':
    # Create required directories
    for directory in ['uploads', 'logs']:
        if not os.path.exists(directory):
            os.makedirs(directory)
    
    # Initialize database
    with app.app_context():
        db.create_all()
    
    # Run application
    app.run(host='0.0.0.0', port=5000, debug=True)