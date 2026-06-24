import urllib.request
import urllib.error
import json
import sqlite3
import random
from datetime import datetime, timedelta

DATABASE = 'bets.db'
API_KEY = '5659792488e64b63abedb36f34674961'
API_HOST = 'api.football-data.org'

# Dicionário de tradução de países para o Português
TRANSLATIONS = {
    'Brazil': 'Brasil',
    'Argentina': 'Argentina',
    'Germany': 'Alemanha',
    'Spain': 'Espanha',
    'France': 'França',
    'England': 'Inglaterra',
    'Switzerland': 'Suíça',
    'Canada': 'Canadá',
    'Bosnia-Herzegovina': 'Bósnia e Herzegovina',
    'Bosnia and Herzegovina': 'Bósnia e Herzegovina',
    'Qatar': 'Catar',
    'Morocco': 'Marrocos',
    'Haiti': 'Haiti',
    'Scotland': 'Escócia',
    'Colombia': 'Colômbia',
    'Congo DR': 'RD Congo',
    'Italy': 'Itália',
    'Netherlands': 'Holanda',
    'Portugal': 'Portugal',
    'Belgium': 'Bélgica',
    'Croatia': 'Croácia',
    'Uruguay': 'Uruguai',
    'USA': 'EUA',
    'United States': 'EUA',
    'Mexico': 'México',
    'Japan': 'Japão',
    'Senegal': 'Senegal',
    'South Korea': 'Coreia do Sul',
    'Saudi Arabia': 'Arábia Saudita',
    'Poland': 'Polônia',
    'Ecuador': 'Equador',
    'Cameroon': 'Camarões',
    'Serbia': 'Sérvia',
    'Ghana': 'Gana',
    'Wales': 'País de Gales',
    'Iran': 'Irã',
    'Denmark': 'Dinamarca'
}

def translate_name(name):
    return TRANSLATIONS.get(name, name)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_from_api(endpoint):
    url = f"https://{API_HOST}/v4/{endpoint}"
    req = urllib.request.Request(url, headers={
        'X-Auth-Token': API_KEY
    })
    try:
        response = urllib.request.urlopen(req)
        data = json.loads(response.read().decode())
        return data
    except urllib.error.HTTPError as e:
        print(f"Erro da API: {e.read().decode()}")
        return None
    except Exception as e:
        print(f"Erro de conexão: {e}")
        return None

def pull_new_games():
    """Busca jogos de hoje da Copa do Mundo e insere como pendentes para apostas."""
    
    # Pegar o dia atual considerando o fuso horário local (UTC-3 do Brasil)
    now_utc = datetime.utcnow()
    now_local = now_utc - timedelta(hours=3)
    today_local_str = now_local.strftime('%Y-%m-%d')
    
    # Buscar numa janela maior na API (ontem, hoje e amanhã no UTC) para não perder nenhum jogo por causa do fuso horário
    date_from = (now_local - timedelta(days=1)).strftime('%Y-%m-%d')
    date_to = (now_local + timedelta(days=1)).strftime('%Y-%m-%d')
    
    data = fetch_from_api(f"competitions/WC/matches?dateFrom={date_from}&dateTo={date_to}")
    
    conn = get_db()
    if not data or 'matches' not in data:
        print("Nenhum dado retornado da API ou API não autorizada.")
        return False
        
    matches = data['matches']
    added = 0
    
    for match in matches:
        # Converter o horário do jogo (que vem em UTC) para o horário local do Brasil (UTC-3)
        match_time_utc = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
        match_time_local = match_time_utc - timedelta(hours=3)
        match_date_local = match_time_local.strftime('%Y-%m-%d')
        
        # Filtra rigorosamente: SÓ JOGOS DO DIA DE HOJE (no fuso do Brasil)
        if match_date_local != today_local_str:
            continue
            
        api_id = match['id']
        team_a_en = match['homeTeam']['name'] if match['homeTeam'].get('name') else 'TBD'
        team_b_en = match['awayTeam']['name'] if match['awayTeam'].get('name') else 'TBD'
        
        # Obter URLs das bandeiras (crests)
        team_a_crest = match['homeTeam'].get('crest', '')
        team_b_crest = match['awayTeam'].get('crest', '')
        
        if team_a_en == 'TBD' or team_b_en == 'TBD':
            continue
            
        # Traduzir os nomes
        team_a = translate_name(team_a_en)
        team_b = translate_name(team_b_en)
        
        # Formatando o horário de exibição HH:MM
        display_time = match_time_local.strftime('%H:%M')
        
        existing_game = conn.execute('SELECT * FROM games WHERE api_id = ?', (api_id,)).fetchone()
        
        if not existing_game:
            conn.execute('''
                INSERT INTO games (team_a, team_b, date, status, api_id, team_a_crest, team_b_crest) 
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
            ''', (team_a, team_b, f"{today_local_str} às {display_time}", api_id, team_a_crest, team_b_crest))
            added += 1
            
    conn.commit()
    conn.close()
    return added > 0

def resolve_pending_games():
    """Busca o resultado real na API para os jogos pendentes e distribui pontos."""
    conn = get_db()
    pending_games = conn.execute('SELECT * FROM games WHERE status = "pending" AND api_id IS NOT NULL').fetchall()
    
    if not pending_games:
        conn.close()
        return False
        
    for game in pending_games:
        api_id = game['api_id']
        game_id = game['id']
        
        match_data = fetch_from_api(f"matches/{api_id}")
        if not match_data:
            continue
            
        status = match_data['status']
        if status not in ['FINISHED', 'AWARDED']:
            continue
            
        score = match_data['score']['fullTime']
        home_goals = score.get('home') or 0
        away_goals = score.get('away') or 0
        
        goals_total = home_goals + away_goals
        winner = 'draw'
        if home_goals > away_goals:
            winner = 'team_a'
        elif away_goals > home_goals:
            winner = 'team_b'
        
        conn.execute('''
            UPDATE games 
            SET status = 'finished', winner = ?, goals_total = ?, shots_total = 0, cards_total = 0, finishes_total = 0
            WHERE id = ?
        ''', (winner, goals_total, game_id))
        
        resolve_bets(conn, game_id, winner, goals_total, home_goals, away_goals)
        
    conn.commit()
    conn.close()
    return True

def resolve_bets(conn, game_id, winner, goals_total, home_goals, away_goals):
    bets = conn.execute('SELECT * FROM bets WHERE game_id = ? AND status = "pending"', (game_id,)).fetchall()
    for bet in bets:
        won = False
        points_awarded = 0
        
        if bet['bet_type'] == 'score':
            # Palpite de placar exato ex: '2-1'
            predicted = bet['prediction']  # ex: '2-1'
            actual = f"{home_goals}-{away_goals}"
            if predicted == actual:
                won = True
                points_awarded = 20  # Placar exato vale mais pontos!
            else:
                # Verifica se pelo menos acertou o vencedor
                parts = predicted.split('-')
                if len(parts) == 2:
                    p_home = int(parts[0])
                    p_away = int(parts[1])
                    predicted_winner = 'draw'
                    if p_home > p_away:
                        predicted_winner = 'team_a'
                    elif p_away > p_home:
                        predicted_winner = 'team_b'
                    if predicted_winner == winner:
                        won = True
                        points_awarded = 5  # Acertou só o vencedor
        elif bet['bet_type'] == 'winner' and bet['prediction'] == winner:
            won = True
            points_awarded = 10
        elif bet['bet_type'] == 'goals' and bet['prediction'] == str(goals_total):
            won = True
            points_awarded = 15
            
        status = 'won' if won else 'lost'
        conn.execute('UPDATE bets SET status = ? WHERE id = ?', (status, bet['id']))
        
        if won:
            conn.execute('''
                UPDATE users 
                SET points = points + ?, correct_bets = correct_bets + 1 
                WHERE id = ?
            ''', (points_awarded, bet['user_id']))

if __name__ == "__main__":
    print("Sincronizando com a API...")
    if pull_new_games():
        print("Sincronização concluída com sucesso.")
    else:
        print("Falha na sincronização.")
