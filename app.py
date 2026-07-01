from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import os
import base64
from datetime import datetime, timedelta
from uuid import uuid4
import database
import sync_api

GAME_DATETIME_FORMAT = '%Y-%m-%d \u00e0s %H:%M'

app = Flask(__name__)
app.secret_key = 'super_secret_key_world_cup'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# In-memory cache for profile images
profile_image_cache = {}
_team_names_synced = False

def get_profile_photo(user_id, profile_photo):
    """Get profile photo from cache first, then from database"""
    if user_id in profile_image_cache:
        return profile_image_cache[user_id]
    if profile_photo:
        # If it's already a base64 data URL, cache it
        if profile_photo.startswith('data:image'):
            profile_image_cache[user_id] = profile_photo
            return profile_photo
        # If it's a file path, convert to base64 and cache
        try:
            file_path = os.path.join(app.root_path, 'static', profile_photo)
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    image_data = f.read()
                extension = profile_photo.rsplit('.', 1)[1].lower()
                base64_data = base64.b64encode(image_data).decode('utf-8')
                data_url = f"data:image/{extension};base64,{base64_data}"
                profile_image_cache[user_id] = data_url
                return data_url
        except Exception as e:
            print(f"Error loading profile photo: {e}")
    return None

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_profile_photo(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def user_is_admin(user_row):
    user = dict(user_row) if user_row else {}
    return (
        user.get('is_admin') in (1, True)
        or (user.get('username') or '').strip().lower() == database.ADMIN_USERNAME
    )

def require_admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = database.get_db()
    user = conn.execute('SELECT username, is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    if not user_is_admin(user):
        flash('Acesso restrito ao administrador.', 'error')
        return redirect(url_for('index'))
    return None

def require_admin_json():
    if 'user_id' not in session:
        return None, jsonify({'success': False, 'message': 'Nao autorizado'}), 401
    conn = database.get_db()
    user = conn.execute('SELECT username, is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if not user_is_admin(user):
        conn.close()
        return None, jsonify({'success': False, 'message': 'Acesso restrito ao administrador'}), 403
    return conn, None, None

def validate_score_prediction(prediction):
    parts = str(prediction).split('-')
    if len(parts) != 2:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3 or int(part) > 999:
            return False
    return True

@app.errorhandler(413)
def request_entity_too_large(error):
    flash('A imagem e muito grande. Envie uma foto com ate 16 MB.')
    if 'user_id' in session:
        return redirect(url_for('profile'))
    return redirect(url_for('login'))

@app.before_request
def setup():
    database.init_db()
    global _team_names_synced
    if not _team_names_synced:
        try:
            sync_api.sync_team_names_in_db()
            _team_names_synced = True
        except Exception:
            pass

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = database.get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Process current user's profile photo and admin status
    user_dict = dict(user)
    user_dict['profile_photo'] = get_profile_photo(user['id'], user['profile_photo'])
    user_dict['is_admin'] = user_is_admin(user)
    
    today_local = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
    games = conn.execute(
        "SELECT * FROM games WHERE status = 'pending' OR date LIKE ? ORDER BY date ASC",
        (f"{today_local}%",)
    ).fetchall()
    users = conn.execute('SELECT id, username, correct_bets, profile_photo FROM users ORDER BY correct_bets DESC, username ASC LIMIT 10').fetchall()
    
    # Process users to use cached profile photos
    users_with_photos = []
    for u in users:
        u_dict = dict(u)
        u_dict['profile_photo'] = get_profile_photo(u['id'], u['profile_photo'])
        users_with_photos.append(u_dict)

    # Determinar quais jogos j? come?aram (bloquear palpites)
    now_local = datetime.utcnow() - timedelta(hours=3)
    locked_games = set()
    for game in games:
        try:
            game_dt = datetime.strptime(game['date'], GAME_DATETIME_FORMAT)
            if now_local >= game_dt:
                locked_games.add(game['id'])
        except (ValueError, TypeError):
            pass

    # Buscar apostas do usu?rio atual para marcar quais j? foram feitas
    user_bets = conn.execute(
        "SELECT game_id, bet_type, prediction, status FROM bets WHERE user_id = ?",
        (session['user_id'],)
    ).fetchall()
    
    # Criar dicion?rio: {game_id: {bet_type: prediction}} e status
    bets_dict = {}
    bets_status = {}
    for b in user_bets:
        if b['game_id'] not in bets_dict:
            bets_dict[b['game_id']] = {}
            bets_status[b['game_id']] = {}
        bets_dict[b['game_id']][b['bet_type']] = b['prediction']
        bets_status[b['game_id']][b['bet_type']] = b['status']
    
    # Apostas de todos os usu?rios agrupadas por jogo
    bet_history = conn.execute('''
        SELECT g.id as game_id, u.id as user_id, u.username, u.profile_photo, b.bet_type, b.prediction, b.status,
               g.team_a, g.team_b, g.date, g.status as game_status,
               g.winner, g.goals_total, g.team_a_goals, g.team_b_goals
        FROM bets b
        JOIN games g ON b.game_id = g.id
        JOIN users u ON b.user_id = u.id
        WHERE g.status = 'pending' OR g.date LIKE ?
        ORDER BY g.date DESC, g.team_a ASC, g.team_b ASC, u.username ASC
    ''', (f"{today_local}%",)).fetchall()

    user_bet_history = conn.execute('''
        SELECT g.id as game_id, b.bet_type, b.prediction, b.status,
               g.team_a, g.team_b, g.date, g.status as game_status,
               g.winner, g.goals_total, g.team_a_goals, g.team_b_goals
        FROM bets b
        JOIN games g ON b.game_id = g.id
        WHERE b.user_id = ? AND (g.status = 'pending' OR g.date LIKE ?)
        ORDER BY g.date DESC, g.team_a ASC, g.team_b ASC
    ''', (session['user_id'], f"{today_local}%")).fetchall()

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
        # Process profile photo for this bet
        bet_dict = dict(bet_item)
        bet_dict['profile_photo'] = get_profile_photo(bet_item['user_id'], bet_item['profile_photo'])
        bet_games_map[game_id]['bets'].append(bet_dict)

    bet_games = list(bet_games_map.values())

    admin_stats = None
    admin_bets = None
    admin_games = None
    if user_dict['is_admin']:
        admin_stats = {
            'total_users': conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'],
            'total_bets': conn.execute('SELECT COUNT(*) as c FROM bets').fetchone()['c'],
            'pending_bets': conn.execute('SELECT COUNT(*) as c FROM bets WHERE status = ?', ('pending',)).fetchone()['c'],
            'finished_games': conn.execute('SELECT COUNT(*) as c FROM games WHERE status = ?', ('finished',)).fetchone()['c'],
            'pending_games': conn.execute('SELECT COUNT(*) as c FROM games WHERE status = ?', ('pending',)).fetchone()['c'],
        }
        admin_bets = conn.execute('''
            SELECT b.id, b.prediction, b.status, b.bet_type,
                   u.username, u.id as user_id,
                   g.id as game_id, g.team_a, g.team_b, g.date,
                   g.status as game_status, g.team_a_goals, g.team_b_goals
            FROM bets b
            JOIN games g ON b.game_id = g.id
            JOIN users u ON b.user_id = u.id
            ORDER BY g.date DESC, u.username ASC
            LIMIT 300
        ''').fetchall()
        admin_games = conn.execute(
            'SELECT * FROM games ORDER BY date DESC LIMIT 100'
        ).fetchall()
        admin_users = conn.execute('SELECT id, username, is_active FROM users ORDER BY username ASC').fetchall()
    
    conn.close()
    return render_template(
        'dashboard.html',
        user=user_dict,
        games=games,
        users=users_with_photos,
        bets_dict=bets_dict,
        bets_status=bets_status,
        locked_games=locked_games,
        bet_games=bet_games,
        user_bet_history=user_bet_history,
        admin_stats=admin_stats,
        admin_bets=admin_bets,
        admin_games=admin_games,
        admin_users=admin_users,
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form.get('password', '').strip()
        if username and password:
            conn = database.get_db()
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if not user:
                cursor = conn.execute('INSERT INTO users (username, password, is_active) VALUES (?, ?, 1)', (username, password))
                user_id = cursor.lastrowid
                conn.commit()
                session['user_id'] = user_id
                conn.close()
                return redirect(url_for('index'))
            else:
                if user.get('is_active') == 0:
                    flash('Usuário inativo. O acesso foi bloqueado.', 'error')
                elif user['password'] == password:
                    session['user_id'] = user['id']
                    conn.close()
                    return redirect(url_for('index'))
                else:
                    flash('Senha incorreta.', 'error')
            conn.close()
    return render_template('login.html')

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
    
    # Process user's profile photo
    user_dict = dict(user)
    user_dict['profile_photo'] = get_profile_photo(user['id'], user['profile_photo'])

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        photo_path = user['profile_photo']

        if not username:
            flash('Informe um nome para o perfil.')
            conn.close()
            return render_template('profile.html', user=user_dict)

        existing = conn.execute(
            'SELECT id FROM users WHERE username = ? AND id <> ?',
            (username, session['user_id'])
        ).fetchone()
        if existing:
            flash('Esse nome de usuario ja esta em uso.')
            conn.close()
            return render_template('profile.html', user=user_dict)

        photo = request.files.get('profile_photo')
        if photo and photo.filename:
            if not allowed_profile_photo(photo.filename):
                flash('Envie uma imagem PNG, JPG, JPEG, GIF ou WEBP.')
                conn.close()
                return render_template('profile.html', user=user_dict)

            # Convert image to base64
            photo_data = photo.read()
            photo_base64 = base64.b64encode(photo_data).decode('utf-8')
            extension = photo.filename.rsplit('.', 1)[1].lower()
            photo_path = f"data:image/{extension};base64,{photo_base64}"
            
            # Cache in memory
            profile_image_cache[session['user_id']] = photo_path

        conn.execute(
            'UPDATE users SET username = ?, profile_photo = ? WHERE id = ?',
            (username, photo_path, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Perfil atualizado com sucesso!')
        return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html', user=user_dict)

@app.route('/pull_games')
def pull_games():
    denied = require_admin()
    if denied:
        return denied
    success = sync_api.pull_new_games()
    if success:
        flash('Novos jogos da Copa foram puxados com sucesso!', 'success')
    else:
        flash('Nenhum jogo novo encontrado ou limite da API atingido.', 'error')
    return redirect(url_for('index'))

@app.route('/resolve_games')
def resolve_games():
    denied = require_admin()
    if denied:
        return denied
    success = sync_api.resolve_pending_games()
    if success:
        flash('Placares atualizados e acertos contabilizados!', 'success')
    else:
        flash('N?o h? jogos pendentes para atualizar ou erro na API.', 'error')
    return redirect(url_for('index'))

@app.route('/admin/edit_bet', methods=['POST'])
def admin_edit_bet():
    conn, error_response, status = require_admin_json()
    if error_response:
        return error_response, status

    data = request.get_json()
    bet_id = data.get('bet_id')
    prediction = data.get('prediction')
    status_val = data.get('status')

    if not bet_id:
        conn.close()
        return jsonify({'success': False, 'message': 'ID da aposta invalido'}), 400

    bet = conn.execute('SELECT * FROM bets WHERE id = ?', (bet_id,)).fetchone()
    if not bet:
        conn.close()
        return jsonify({'success': False, 'message': 'Aposta nao encontrada'}), 404

    prediction_changed = False
    if prediction is not None:
        if bet['bet_type'] == 'score' and not validate_score_prediction(prediction):
            conn.close()
            return jsonify({'success': False, 'message': 'Placar invalido'}), 400
        conn.execute('UPDATE bets SET prediction = ? WHERE id = ?', (prediction, bet_id))
        prediction_changed = True

    status_changed = False
    if status_val is not None and status_val in ('pending', 'won', 'lost'):
        conn.execute('UPDATE bets SET status = ? WHERE id = ?', (status_val, bet_id))
        status_changed = True

    if prediction_changed:
        sync_api.revalidate_all_bets(conn)
    elif status_changed:
        sync_api.recalculate_user_scores(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Aposta atualizada!'})

@app.route('/admin/delete_bet', methods=['POST'])
def admin_delete_bet():
    conn, error_response, status = require_admin_json()
    if error_response:
        return error_response, status

    data = request.get_json()
    bet_id = data.get('bet_id')
    if not bet_id:
        conn.close()
        return jsonify({'success': False, 'message': 'ID da aposta invalido'}), 400

    bet = conn.execute('SELECT id FROM bets WHERE id = ?', (bet_id,)).fetchone()
    if not bet:
        conn.close()
        return jsonify({'success': False, 'message': 'Aposta nao encontrada'}), 404

    conn.execute('DELETE FROM bets WHERE id = ?', (bet_id,))
    sync_api.revalidate_all_bets(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Aposta removida!'})

@app.route('/admin/edit_game', methods=['POST'])
def admin_edit_game():
    conn, error_response, status = require_admin_json()
    if error_response:
        return error_response, status

    data = request.get_json()
    game_id = data.get('game_id')
    team_a_goals = data.get('team_a_goals')
    team_b_goals = data.get('team_b_goals')
    game_status = data.get('status')

    if not game_id:
        conn.close()
        return jsonify({'success': False, 'message': 'ID do jogo invalido'}), 400

    game = conn.execute('SELECT * FROM games WHERE id = ?', (game_id,)).fetchone()
    if not game:
        conn.close()
        return jsonify({'success': False, 'message': 'Jogo nao encontrado'}), 404

    if team_a_goals is not None and team_b_goals is not None:
        try:
            a_goals = int(team_a_goals)
            b_goals = int(team_b_goals)
            if a_goals < 0 or b_goals < 0 or a_goals > 999 or b_goals > 999:
                raise ValueError()
        except (ValueError, TypeError):
            conn.close()
            return jsonify({'success': False, 'message': 'Placar invalido'}), 400

        goals_total = a_goals + b_goals
        winner = 'draw'
        if a_goals > b_goals:
            winner = 'team_a'
        elif b_goals > a_goals:
            winner = 'team_b'

        new_status = game_status if game_status in ('pending', 'finished') else 'finished'
        conn.execute('''
            UPDATE games SET status = ?, winner = ?, goals_total = ?,
                             team_a_goals = ?, team_b_goals = ?
            WHERE id = ?
        ''', (new_status, winner, goals_total, a_goals, b_goals, game_id))
    elif game_status in ('pending', 'finished'):
        conn.execute('UPDATE games SET status = ? WHERE id = ?', (game_status, game_id))

    sync_api.revalidate_all_bets(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Jogo atualizado!'})

@app.route('/admin/recalculate', methods=['POST'])
def admin_recalculate():
    conn, error_response, status = require_admin_json()
    if error_response:
        return error_response, status

    sync_api.revalidate_all_bets(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Ranking recalculado!'})

@app.route('/admin/toggle_user', methods=['POST'])
def admin_toggle_user():
    conn, error_response, status = require_admin_json()
    if error_response: return error_response, status
    data = request.get_json()
    target_id = data.get('user_id')
    is_active = data.get('is_active')
    
    if target_id == session['user_id']:
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível inativar a si mesmo.'})
        
    conn.execute('UPDATE users SET is_active = ? WHERE id = ?', (is_active, target_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Status do usuário atualizado!'})

@app.route('/bet', methods=['POST'])
def bet():
    """Rota AJAX para registrar apostas diretamente do dashboard."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'N?o autorizado'}), 401

    data = request.get_json()
    game_id = data.get('game_id')
    bet_type = data.get('bet_type')
    prediction = data.get('prediction')

    if not game_id or not bet_type or not prediction:
        return jsonify({'success': False, 'message': 'Dados inv?lidos'}), 400

    if bet_type == 'score':
        parts = str(prediction).split('-')
        if len(parts) != 2:
            return jsonify({'success': False, 'message': 'Placar inv?lido'}), 400
        for part in parts:
            if not part.isdigit() or len(part) > 3 or int(part) > 999:
                return jsonify({'success': False, 'message': 'Placar inv?lido. Use at? 3 n?meros por time (ex: 100 x 100).'}), 400

    conn = database.get_db()
    
    # Verificar se o jogo ainda est? pendente
    game = conn.execute('SELECT status, date FROM games WHERE id = ?', (game_id,)).fetchone()
    if not game or game['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'message': 'Jogo n?o dispon?vel para apostas'})

    # Verificar se o jogo j? come?ou pelo hor?rio
    try:
        game_datetime = datetime.strptime(game['date'], GAME_DATETIME_FORMAT)
        now_local = datetime.utcnow() - timedelta(hours=3)
        if now_local >= game_datetime:
            conn.close()
            return jsonify({'success': False, 'message': 'Jogo j? iniciou! N?o ? poss?vel registrar palpites.'})
    except (ValueError, TypeError):
        pass

    # Verificar se j? apostou nesse tipo para esse jogo
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
    
    # Process users to use cached profile photos
    users_with_photos = []
    for u in users:
        u_dict = dict(u)
        u_dict['profile_photo'] = get_profile_photo(u['id'], u['profile_photo'])
        users_with_photos.append(u_dict)
    
    conn.close()
    return render_template('leaderboard.html', users=users_with_photos)

@app.route('/historico')
def historico():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = database.get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Process user's profile photo
    user_dict = dict(user)
    user_dict['profile_photo'] = get_profile_photo(user['id'], user['profile_photo'])

    bets = conn.execute('''
        SELECT b.bet_type, b.prediction, b.status,
               g.team_a, g.team_b, g.date, g.status as game_status,
               g.team_a_goals, g.team_b_goals, g.team_a_crest, g.team_b_crest
        FROM bets b
        JOIN games g ON b.game_id = g.id
        WHERE b.user_id = ?
        ORDER BY g.date DESC, g.team_a ASC
    ''', (session['user_id'],)).fetchall()

    total = len(bets)
    won = sum(1 for b in bets if b['status'] == 'won')
    lost = sum(1 for b in bets if b['status'] == 'lost')
    pending = sum(1 for b in bets if b['status'] == 'pending')

    conn.close()
    return render_template('historico.html', user=user_dict, bets=bets,
                           total=total, won=won, lost=lost, pending=pending)

@app.route('/admin/hard_reset')
def admin_hard_reset():
    denied = require_admin()
    if denied:
        return denied
    conn = database.get_db()
    conn.execute('DELETE FROM bets')
    conn.execute('DELETE FROM games')
    conn.execute('DELETE FROM users WHERE username != ?', ('herbert',))
    conn.execute('UPDATE users SET correct_bets = 0, points = 0 WHERE username = ?', ('herbert',))
    h = conn.execute('SELECT id FROM users WHERE username = ?', ('herbert',)).fetchone()
    if not h:
        conn.execute("INSERT INTO users (username, password, is_admin) VALUES ('herbert', '123', 1)")
    else:
        conn.execute("UPDATE users SET password = '123', is_admin = 1 WHERE username = 'herbert'")
    conn.commit()
    conn.close()
    flash('Banco de dados de produção limpo. Apenas herbert foi mantido.', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
