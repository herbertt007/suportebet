from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
from uuid import uuid4
import database
import sync_api

app = Flask(__name__)
app.secret_key = 'super_secret_key_world_cup'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_profile_photo(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

@app.errorhandler(413)
def request_entity_too_large(error):
    flash('A imagem e muito grande. Envie uma foto com ate 16 MB.')
    if 'user_id' in session:
        return redirect(url_for('profile'))
    return redirect(url_for('login'))

@app.before_request
def setup():
    database.init_db()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = database.get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    today_local = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
    games = conn.execute(
        "SELECT * FROM games WHERE date LIKE ? ORDER BY date ASC",
        (f"{today_local}%",)
    ).fetchall()
    users = conn.execute('SELECT username, correct_bets, profile_photo FROM users ORDER BY correct_bets DESC, username ASC LIMIT 10').fetchall()
    
    # Buscar apostas do usuário atual para marcar quais já foram feitas
    user_bets = conn.execute(
        "SELECT game_id, bet_type, prediction, status FROM bets WHERE user_id = ?",
        (session['user_id'],)
    ).fetchall()
    
    # Criar dicionário: {game_id: {bet_type: prediction}}
    bets_dict = {}
    for b in user_bets:
        if b['game_id'] not in bets_dict:
            bets_dict[b['game_id']] = {}
        bets_dict[b['game_id']][b['bet_type']] = b['prediction']
    
    # Apostas de todos os usuários agrupadas por jogo
    bet_history = conn.execute('''
        SELECT g.id as game_id, u.username, u.profile_photo, b.bet_type, b.prediction, b.status,
               g.team_a, g.team_b, g.date, g.status as game_status,
               g.winner, g.goals_total, g.team_a_goals, g.team_b_goals
        FROM bets b
        JOIN games g ON b.game_id = g.id
        JOIN users u ON b.user_id = u.id
        ORDER BY g.date DESC, g.team_a ASC, g.team_b ASC, u.username ASC
    ''').fetchall()

    user_bet_history = conn.execute('''
        SELECT g.id as game_id, b.bet_type, b.prediction, b.status,
               g.team_a, g.team_b, g.date, g.status as game_status,
               g.winner, g.goals_total, g.team_a_goals, g.team_b_goals
        FROM bets b
        JOIN games g ON b.game_id = g.id
        WHERE b.user_id = ?
        ORDER BY g.date DESC, g.team_a ASC, g.team_b ASC
    ''', (session['user_id'],)).fetchall()

    bet_games_map = {}
    for bet_item in bet_history:
        game_id = bet_item['game_id']
        if game_id not in bet_games_map:
            bet_games_map[game_id] = {
                'game_id': game_id,
                'team_a': bet_item['team_a'],
                'team_b': bet_item['team_b'],
                'date': bet_item['date'],
                'game_status': bet_item['game_status'],
                'winner': bet_item['winner'],
                'goals_total': bet_item['goals_total'],
                'team_a_goals': bet_item['team_a_goals'],
                'team_b_goals': bet_item['team_b_goals'],
                'bets': []
            }
        bet_games_map[game_id]['bets'].append(bet_item)

    bet_games = list(bet_games_map.values())
    
    conn.close()
    return render_template(
        'dashboard.html',
        user=user,
        games=games,
        users=users,
        bets_dict=bets_dict,
        bet_games=bet_games,
        user_bet_history=user_bet_history
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form.get('password', '').strip()
        if username and password:
            conn = database.get_db()
            user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
            if not user:
                flash('Usuário ou senha incorretos, ou usuário não cadastrado.', 'error')
            else:
                session['user_id'] = user['id']
                conn.close()
                return redirect(url_for('index'))
            conn.close()
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form.get('password', '').strip()
        if username and password:
            conn = database.get_db()
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user:
                flash('Usuário já existe. Faça o login.', 'error')
            else:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
                conn.commit()
                flash('Cadastro realizado com sucesso! Faça login.', 'success')
                conn.close()
                return redirect(url_for('login'))
            conn.close()
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = database.get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if not user:
        conn.close()
        session.pop('user_id', None)
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        photo_path = user['profile_photo']

        if not username:
            flash('Informe um nome para o perfil.')
            conn.close()
            return render_template('profile.html', user=user)

        existing = conn.execute(
            'SELECT id FROM users WHERE username = ? AND id <> ?',
            (username, session['user_id'])
        ).fetchone()
        if existing:
            flash('Esse nome de usuario ja esta em uso.')
            conn.close()
            return render_template('profile.html', user=user)

        photo = request.files.get('profile_photo')
        if photo and photo.filename:
            if not allowed_profile_photo(photo.filename):
                flash('Envie uma imagem PNG, JPG, JPEG, GIF ou WEBP.')
                conn.close()
                return render_template('profile.html', user=user)

            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            original_name = secure_filename(photo.filename)
            extension = original_name.rsplit('.', 1)[1].lower()
            filename = f"profile-{session['user_id']}-{uuid4().hex}.{extension}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            photo_path = f"uploads/{filename}"

        conn.execute(
            'UPDATE users SET username = ?, profile_photo = ? WHERE id = ?',
            (username, photo_path, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Perfil atualizado com sucesso!')
        return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html', user=user)

@app.route('/pull_games')
def pull_games():
    success = sync_api.pull_new_games()
    if success:
        flash('Novos jogos da Copa foram puxados com sucesso!', 'success')
    else:
        flash('Nenhum jogo novo encontrado ou limite da API atingido.', 'error')
    return redirect(url_for('index'))

@app.route('/resolve_games')
def resolve_games():
    success = sync_api.resolve_pending_games()
    if success:
        flash('Placares atualizados e acertos contabilizados!', 'success')
    else:
        flash('Não há jogos pendentes para atualizar ou erro na API.', 'error')
    return redirect(url_for('index'))

@app.route('/bet', methods=['POST'])
def bet():
    """Rota AJAX para registrar apostas diretamente do dashboard."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401

    data = request.get_json()
    game_id = data.get('game_id')
    bet_type = data.get('bet_type')
    prediction = data.get('prediction')

    if not game_id or not bet_type or not prediction:
        return jsonify({'success': False, 'message': 'Dados inválidos'}), 400

    conn = database.get_db()
    
    # Verificar se o jogo ainda está pendente
    game = conn.execute('SELECT status FROM games WHERE id = ?', (game_id,)).fetchone()
    if not game or game['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'message': 'Jogo não disponível para apostas'})

    # Verificar se já apostou nesse tipo para esse jogo
    existing = conn.execute(
        'SELECT id FROM bets WHERE user_id = ? AND game_id = ? AND bet_type = ?',
        (session['user_id'], game_id, bet_type)
    ).fetchone()

    if existing:
        # Atualiza a aposta existente
        conn.execute(
            'UPDATE bets SET prediction = ? WHERE user_id = ? AND game_id = ? AND bet_type = ?',
            (prediction, session['user_id'], game_id, bet_type)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Aposta atualizada!'})
    else:
        conn.execute(
            'INSERT INTO bets (user_id, game_id, bet_type, prediction) VALUES (?, ?, ?, ?)',
            (session['user_id'], game_id, bet_type, prediction)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Aposta registrada!'})

@app.route('/leaderboard')
def leaderboard():
    conn = database.get_db()
    users = conn.execute('SELECT * FROM users ORDER BY correct_bets DESC, username ASC').fetchall()
    conn.close()
    return render_template('leaderboard.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)
