from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Secure random key for session management

# MySQL Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://change_user:change_password@localhost/db_name'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Initialize the database
db = SQLAlchemy(app)

# Database Models
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


if __name__ == '__main__':
    app.run(debug=True)