import urllib.request
import urllib.error
import json
import os
from datetime import datetime, timedelta
import database

API_KEY = '5659792488e64b63abedb36f34674961'
API_HOST = 'api.football-data.org'

# Dicionário de tradução de seleções para Português Brasileiro
TRANSLATIONS = {
    'Albania': 'Albânia',
    'Algeria': 'Argélia',
    'Angola': 'Angola',
    'Argentina': 'Argentina',
    'Australia': 'Austrália',
    'Austria': 'Áustria',
    'Bahrain': 'Bahrein',
    'Belgium': 'Bélgica',
    'Bolivia': 'Bolívia',
    'Bosnia and Herzegovina': 'Bósnia e Herzegovina',
    'Bosnia-Herzegovina': 'Bósnia e Herzegovina',
    'Brazil': 'Brasil',
    'Burkina Faso': 'Burkina Faso',
    'Cameroon': 'Camarões',
    'Canada': 'Canadá',
    'Cape Verde': 'Cabo Verde',
    'Cape Verde Islands': 'Cabo Verde',
    'Chile': 'Chile',
    'China': 'China',
    'China PR': 'China',
    'Colombia': 'Colômbia',
    'Congo DR': 'RD Congo',
    'Costa Rica': 'Costa Rica',
    'Croatia': 'Croácia',
    'Curacao': 'Curaçao',
    'Curaçao': 'Curaçao',
    'Côte d\'Ivoire': 'Costa do Marfim',
    'Czech Republic': 'República Tcheca',
    'Czechia': 'República Tcheca',
    'DR Congo': 'RD Congo',
    'Denmark': 'Dinamarca',
    'Ecuador': 'Equador',
    'Egypt': 'Egito',
    'El Salvador': 'El Salvador',
    'England': 'Inglaterra',
    'Ethiopia': 'Etiópia',
    'Finland': 'Finlândia',
    'France': 'França',
    'Germany': 'Alemanha',
    'Ghana': 'Gana',
    'Greece': 'Grécia',
    'Guinea': 'Guiné',
    'Guinea-Bissau': 'Guiné-Bissau',
    'Haiti': 'Haiti',
    'Honduras': 'Honduras',
    'Hungary': 'Hungria',
    'Iceland': 'Islândia',
    'India': 'Índia',
    'Indonesia': 'Indonésia',
    'Iran': 'Irã',
    'Iraq': 'Iraque',
    'Ireland': 'Irlanda',
    'Italy': 'Itália',
    'Republic of Ireland': 'Irlanda',
    'Ivory Coast': 'Costa do Marfim',
    'Jamaica': 'Jamaica',
    'Japan': 'Japão',
    'Jordan': 'Jordânia',
    'Kenya': 'Quênia',
    'Kuwait': 'Kuwait',
    'Libya': 'Líbia',
    'Mali': 'Mali',
    'Mexico': 'México',
    'Morocco': 'Marrocos',
    'Mozambique': 'Moçambique',
    'Netherlands': 'Holanda',
    'New Zealand': 'Nova Zelândia',
    'Nigeria': 'Nigéria',
    'Northern Ireland': 'Irlanda do Norte',
    'Norway': 'Noruega',
    'Oman': 'Omã',
    'Panama': 'Panamá',
    'Paraguay': 'Paraguai',
    'Peru': 'Peru',
    'Poland': 'Polônia',
    'Portugal': 'Portugal',
    'Qatar': 'Catar',
    'Romania': 'Romênia',
    'Saudi Arabia': 'Arábia Saudita',
    'Scotland': 'Escócia',
    'Senegal': 'Senegal',
    'Serbia': 'Sérvia',
    'Slovakia': 'Eslováquia',
    'Slovenia': 'Eslovênia',
    'South Africa': 'África do Sul',
    'South Korea': 'Coreia do Sul',
    'Korea Republic': 'Coreia do Sul',
    'Spain': 'Espanha',
    'Sweden': 'Suécia',
    'Switzerland': 'Suíça',
    'Thailand': 'Tailândia',
    'Trinidad and Tobago': 'Trinidad e Tobago',
    'Tunisia': 'Tunísia',
    'Turkey': 'Turquia',
    'Türkiye': 'Turquia',
    'UAE': 'Emirados Árabes Unidos',
    'USA': 'EUA',
    'Uganda': 'Uganda',
    'Ukraine': 'Ucrânia',
    'United Arab Emirates': 'Emirados Árabes Unidos',
    'United States': 'EUA',
    'Uruguay': 'Uruguai',
    'Uzbekistan': 'Uzbequistão',
    'Venezuela': 'Venezuela',
    'Vietnam': 'Vietnã',
    'Wales': 'País de Gales',
    'Zambia': 'Zâmbia',
}

def translate_name(name):
    return TRANSLATIONS.get(name, name)

def sync_team_names_in_db():
    """Atualiza nomes em inglês já salvos no banco para português."""
    conn = database.get_db()
    games = conn.execute('SELECT id, team_a, team_b FROM games').fetchall()
    updated = 0
    for game in games:
        team_a = translate_name(game['team_a'])
        team_b = translate_name(game['team_b'])
        if team_a != game['team_a'] or team_b != game['team_b']:
            conn.execute(
                'UPDATE games SET team_a = ?, team_b = ? WHERE id = ?',
                (team_a, team_b, game['id'])
            )
            updated += 1
    if updated:
        conn.commit()
    conn.close()
    return updated

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
    """Busca jogo do Brasil (de hoje ou o próximo) e insere como pendente para apostas."""
    sync_team_names_in_db()
    
    # Pegar o dia atual considerando o fuso horário local (UTC-3 do Brasil)
    now_utc = datetime.utcnow()
    now_local = now_utc - timedelta(hours=3)
    today_local_str = now_local.strftime('%Y-%m-%d')
    
    # Buscar numa janela maior na API (até 60 dias) para encontrar o próximo jogo do Brasil
    date_from = now_local.strftime('%Y-%m-%d')
    date_to = (now_local + timedelta(days=60)).strftime('%Y-%m-%d')
    
    data = fetch_from_api(f"competitions/WC/matches?dateFrom={date_from}&dateTo={date_to}")
    
    conn = database.get_db()
    if not data or 'matches' not in data:
        print("Nenhum dado retornado da API ou API não autorizada.")
        conn.close()
        return False
        
    matches = data['matches']
    
    # Filtrar apenas jogos do Brasil
    brazil_matches = []
    for match in matches:
        team_a_en = match['homeTeam']['name'] if match['homeTeam'].get('name') else 'TBD'
        team_b_en = match['awayTeam']['name'] if match['awayTeam'].get('name') else 'TBD'
        if 'Brazil' in [team_a_en, team_b_en]:
            brazil_matches.append(match)

    if not brazil_matches:
        conn.close()
        return False
        
    # Ordenar por data
    brazil_matches.sort(key=lambda x: x['utcDate'])
    
    # Encontrar o jogo de hoje; se não houver, pegar o próximo (o primeiro da lista)
    target_match = None
    for match in brazil_matches:
        match_time_utc = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
        match_time_local = match_time_utc - timedelta(hours=3)
        match_date_local = match_time_local.strftime('%Y-%m-%d')
        
        if match_date_local == today_local_str:
            target_match = match
            break
            
    if not target_match:
        target_match = brazil_matches[0]

    added = 0
    match = target_match
    
    match_time_utc = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
    match_time_local = match_time_utc - timedelta(hours=3)
    match_date_local = match_time_local.strftime('%Y-%m-%d')
    
    api_id = match['id']
    team_a_en = match['homeTeam']['name'] if match['homeTeam'].get('name') else 'TBD'
    team_b_en = match['awayTeam']['name'] if match['awayTeam'].get('name') else 'TBD'
    
    # Obter URLs das bandeiras (crests)
    team_a_crest = match['homeTeam'].get('crest', '')
    team_b_crest = match['awayTeam'].get('crest', '')
    
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
        ''', (team_a, team_b, f"{match_date_local} às {display_time}", api_id, team_a_crest, team_b_crest))
        added += 1
            
    conn.commit()
    conn.close()
    return added > 0

def resolve_pending_games():
    """Busca resultado real na API e revalida todos os palpites por placar exato."""
    conn = database.get_db()
    # Incluir jogos finalizados sem placar para corrigir dados antigos
    games_to_resolve = conn.execute("""
        SELECT * FROM games
        WHERE api_id IS NOT NULL
        AND (status = 'pending' OR (status = 'finished' AND (team_a_goals IS NULL OR team_b_goals IS NULL)))
    """).fetchall()

    for game in games_to_resolve:
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
            SET status = 'finished', winner = ?, goals_total = ?, team_a_goals = ?, team_b_goals = ?,
                shots_total = 0, cards_total = 0, finishes_total = 0
            WHERE id = ?
        ''', (winner, goals_total, home_goals, away_goals, game_id))

    # Revalidar TODOS os palpites de jogos finalizados com placar exato
    revalidate_all_bets(conn)

    conn.commit()
    conn.close()
    return True


def revalidate_all_bets(conn):
    """Revalida todas as apostas por placar exato e recalcula acertos de cada usuario."""
    finished_games = conn.execute("""
        SELECT id, team_a_goals, team_b_goals FROM games
        WHERE status = 'finished' AND team_a_goals IS NOT NULL AND team_b_goals IS NOT NULL
    """).fetchall()

    for game in finished_games:
        actual = f"{game['team_a_goals']}-{game['team_b_goals']}"
        bets = conn.execute("SELECT * FROM bets WHERE game_id = ?", (game['id'],)).fetchall()
        for bet in bets:
            won = (bet['bet_type'] == 'score' and bet['prediction'] == actual)
            conn.execute('UPDATE bets SET status = ? WHERE id = ?',
                         ('won' if won else 'lost', bet['id']))

    # Recalcular correct_bets e points do zero para todos os usuarios
    conn.execute('UPDATE users SET correct_bets = 0, points = 0')
    user_wins = conn.execute("""
        SELECT user_id, COUNT(*) as wins FROM bets WHERE status = 'won' GROUP BY user_id
    """).fetchall()
    for uw in user_wins:
        conn.execute('UPDATE users SET correct_bets = ?, points = ? WHERE id = ?',
                     (uw['wins'], uw['wins'] * 20, uw['user_id']))

def recalculate_user_scores(conn):
    """Recalcula acertos e pontos sem alterar status das apostas."""
    conn.execute('UPDATE users SET correct_bets = 0, points = 0')
    user_wins = conn.execute("""
        SELECT user_id, COUNT(*) as wins FROM bets WHERE status = 'won' GROUP BY user_id
    """).fetchall()
    for uw in user_wins:
        conn.execute('UPDATE users SET correct_bets = ?, points = ? WHERE id = ?',
                     (uw['wins'], uw['wins'] * 20, uw['user_id']))

if __name__ == "__main__":
    print("Sincronizando com a API...")
    if pull_new_games():
        print("Sincronização concluída com sucesso.")
    else:
        print("Falha na sincronização.")
