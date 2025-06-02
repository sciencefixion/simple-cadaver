from flask import Flask, render_template, request, redirect, url_for, session
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.route('/', methods=['GET', 'POST'])
def home():
    # Initialize session variables if they don't exist
    if 'story' not in session:
        session['story'] = []
    if 'current_player' not in session:
        session['current_player'] = 1
    if 'max_players' not in session:
        session['max_players'] = 3  # Default number of players
    if 'round' not in session:
        session['round'] = 1
        
    if request.method == 'POST':
        # Handle form submission to set number of players
        session['max_players'] = int(request.form['player_count'])
        session['current_player'] = 1
        session['story'] = []
        session['round'] = 1
        return redirect(url_for('game'))
    
    return render_template('setup.html')

@app.route('/game', methods=['GET', 'POST'])
def game():
    # Initialize session variables if they don't exist
    if 'story' not in session:
        session['story'] = []
    if 'current_player' not in session:
        session['current_player'] = 1
    if 'max_players' not in session:
        session['max_players'] = 3
    if 'round' not in session:
        session['round'] = 1

    if request.method == 'POST':
        # Add the player's contribution to the story
        contribution = request.form['contribution']
        session['story'].append(contribution)
        
        # Move to next player or next round
        if session['current_player'] < session['max_players']:
            session['current_player'] += 1
        else:
            session['current_player'] = 1
            session['round'] += 1
        
        # Check if game is over (3 rounds by default)
        if session['round'] > 3:
            return redirect(url_for('result'))
    
    # Determine if we should show input or wait screen
    show_input = session['current_player'] == 1 or 'show_all' in request.args
    
    # Get only the last contribution for display (or empty if first turn)
    last_contribution = session['story'][-1] if session['story'] else ""
    
    return render_template('game.html', 
                        last_contribution=last_contribution,
                        current_player=session['current_player'],
                        max_players=session['max_players'],
                        round=session['round'],
                        show_input=show_input)

@app.route('/result')
def result():
    full_story = "\n".join(session['story'])
    return render_template('result.html', story=full_story)

if __name__ == '__main__':
    app.run(debug=True)