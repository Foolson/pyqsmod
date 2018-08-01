#!/usr/bin/python

#   pyqsmod
#
#   Parse OpenArena/Quake3 logs and output multiple lists with rank data and
#   stats.
#
#   Based on pyqscore written by Jose Rodriguez which created .html-files
#   with leaderboards.
#
#   Copyright (C) 2011  Jose Rodriguez
#   Copyright (C) 2018  Johan Olsson
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, version 2.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
from datetime import timedelta
from random import randint

__author__ = "Johan Olsson"
__version__ = "1.0.0"
__date__ = "2018-08-01"
__license__ = "GPLv2"
__copyright__ = "Copyright (C) 2011  Jose Rodriguez, \
    Copyright (C) 2018  Johan Olsson"

# =======================         OPTIONS         ======================= #

MAXPLAYERS = 150
# Maximum number of players displayed in HTML output

SORT_OPTION = 'time'
# How to sort table columns. Options: deaths, frag_death_ratio,
# frags, games, ping, time, won, won_percentage

BAN_LIST = ['UnnamedPlayer', 'a_player_I_dont_like']
# Comma-separated list containing the nicks of undesired players.
# Nicks must include the colour codes and be inside quotes.

MINPLAY = 0.5
# From 0 to 1, minimum fraction of time a player has to play in a game
# relative to that of the player who played for longer in order appear
# in the statistics. Example: Player A is the first player joining a
# match. The match lasts for 10 minutes. If MINPLAY is 0.7, only the
# statistics of players who joined during the first 3 minutes will count.

NUMBER_OF_QUOTES = 15
# Number of random quotes displayed

GTYPE_OVERRIDE = ''
# If you have a mixed log with different game types, this will override
# the game type read from the log. You can type what you want here.

DISPLAY_CTF_TABLE = True
# Display or not the CTF table in the HTML output. This will only work
# if there are players with CTF-related data (True/False)

# ====================================================================== #


class Game:
    '''Class with no methods used to store game data'''

    def __init__(self, number):
        self.number = number  # game number
        self.mapname = []
        self.players = {}  # nick: (ping, position)
        self.pid = {}  # player id
        self.handicap = {}
        self.teams = {}
        self.scores = []
        self.awards = {}
        self.itemsp = {}
        self.killsp = {}  # world frags and suicides
        self.deathsp = {}  # deaths caused by other players
        self.ctf = {}  # 0: flag taken; 1: capture
        self.killsp['<world>'] = []
        self.ptime = {}  # Player time
        self.time = 0  # Game time
        self.validp = []  # Valid game flag
        self.quotes = set()
        self.weapons = {}


class Server:
    '''Another class to store server data'''

    def __init__(self):
        self.time = 0
        self.frags = 0
        self.gtype = 0


def read_log(log_file):
    '''Reads log file and outputs dictionary storing lines'''

    Nlines = 1

    log = {}
    count = 1
    k_new = 0

    with open(log_file, 'r') as f:
        for line in f:
            # Ignore lines from previous runs
            if count < Nlines:
                pass
            else:
                log[count] = line
                k_new += 1
            count += 1
    return log


def mainProcessing(log):
    '''Main processing function'''

    server = Server()
    cgames = []  # Cumulative list of games: instances of Game()
    N = 1  # Game number
    lines = (line for line in log.values())
    for line in lines:
        # New game started (no warmup). Begin to parse stuff
        if line.find(' InitGame: ') > 0 and next(lines).find(' Warmup:') == -1:
            game = Game(N)
            N += 1
            game.pos = 1  # Player's score position
            game, server = lineProcInit(line, game, server)
            game, server, valid_game = oneGameProc(lines, game, server)
            if valid_game:
                if len(game.players) == 0:
                    continue

                server.time = server.time + \
                    game.time - min(game.ptime.values())

                cgames.append(game)  # Append game to list of games
    return server, cgames


def lineProcInit(line, game, server):
    '''Process game init lines'''

    regex = re.compile(r'mapname[\\]([\w]*)')
    mapname = regex.search(line).group(1)
    game.mapname = mapname

    idx = line.find('sv_hostname') + 11
    hostname = line[idx:idx+50].split('\\')[1]  # Does this always work?
    server.hostname = hostname  # I hope so anyway

    idx = line.find('g_gametype')
    game.gametype = line[idx+11]
    try:
        server.gtype = int(game.gametype)
    except(ValueError):
        server.gtype = 0  # Default to DM if bad things happen
    return game, server


def oneGameProc(lines, game, server):
    '''Process lines from one single game'''

    valid_game = False
    for line in lines:
        # Process more frequent lines first: Items >> Kill > Userinfo > Awards
        if line.find(' Item: ') > 0:
            # I don't need items at the moment, so pass and save a lot of time.
            # If they are needed the following function provide everything
            # required to keep track of the items collected by each player.
            continue
        elif line.find(' Kill: ') > 0:
            game, server = lineProcKills(line, game, server)
        elif line.find(' CTF: ') > 0:
            game = lineProcCTF(line, game)
        elif line.find(' Award: ') > 0:
            game = lineProcAwards(line, game)
        elif line.find('UserinfoChanged') > 0:
            game = lineProcUserInfo(line, game)
        elif line.find(' say:') > 0:
            game = lineProcQuotes(line, game)
        elif line.find(' score: ') > 0:
            game = lineProcScores(line, game)
        elif line.find(' red:') > 0:
            game.ctfscores = (line[11], line[19])
        elif ((line.find('Exit: Timelimit hit') > 0) or
              (line.find('Exit: Fraglimit hit') > 0) or
              (line.find('Exit: Capturelimit hit') > 0)):
            # Game completed. Make a note of the time and flag it as valid.
            e_idx = line.find('Exit')
            game.time = totime(line[0:e_idx])
            valid_game = True
        elif line.find(' ShutdownGame:') > 0:
            break
    return game, server, valid_game


def lineProcKills(this_line, game, server):
    '''Process kill lines'''

    k_idx = this_line.find(' killed ')
    # If somebody's nick contains the string ' killed ',
    # we're screwed

    regex = re.compile(r'\d:[\s](.*)')  # Fragger's nick
    try:
        # Does this really need a try/except clause?
        killer = regex.search(this_line[17:k_idx]).group(1)
    except:
        return game, server

    d_idx = k_idx + 6
    b_idx = this_line.rfind(' b')
    killed = this_line[d_idx + 2:b_idx]  # Victim
    weapon = this_line[b_idx + 7 + 1:-1]  # Weapon
    # try statement needed to avoid rare cases of damaged logs:
    # We're looking stuff up on a dictionary, so if the line is
    # broken the key may not exist and python complains
    try:
        if killer == killed:
            game.killsp[killer].append(weapon)
        elif killer != '<world>':
            game.weapons[killer][weapon[0:3]] = (
                                    game.weapons[killer][weapon[0:3]] + 1)
        else:
            game.killsp['<world>'].append(killed)
        game.deathsp[killed] = game.deathsp[killed] + 1
    except:
        pass
    else:
        server.frags += 1
    return game, server


def lineProcCTF(this_line, game):
    '''Process CTF lines'''

    p_id = this_line[12]  # Player ID
    event = this_line[16]
    try:
        game.ctf[game.pid[p_id]][event] = game.ctf[game.pid[p_id]][event] + 1
    except:
        pass
    return game


def lineProcAwards(this_line, game):
    '''Process line awards lines'''

    g_idx = this_line.find(' gained ')
    regex = re.compile(r'\d:\s(\S*\s?\S*)')  # Player name
    result = regex.search(this_line[0:g_idx])
    # Assist, Capture, Defence, Impressive, Excellent
    name, award = [result.group(1), this_line[g_idx+12:g_idx+13]]
    try:
        game.awards[name][award] = game.awards[name][award] + 1
    except:
        pass
    return game


def lineProcUserInfo(this_line, game):
    '''Process user info lines'''

    regex = re.compile(r'Changed:[\s]([\d]*)')  # client id
    new_id = regex.search(this_line).group(1)
    regex = re.compile(r'n\\([^\\]*)')  # client name
    new_name = regex.search(this_line).group(1)
    try:
        regex = re.compile(r'\\hc\\(\d*)')  # handicap
        handicap = regex.search(this_line).group(1)
    except:
        handicap = 100

    regex = re.compile(r'\\t\\(\d)')
    team = regex.search(this_line).group(1)

    if new_name not in game.pid.values():
        # Initialize dictionaries for new player
        game.itemsp[new_name] = []
        game.killsp[new_name] = []
        game.deathsp[new_name] = 0
        game.awards[new_name] = {'A': 0, 'C': 0, 'D': 0, 'E': 0, 'I': 0}
        game.handicap[new_name] = handicap
        game.teams[new_name] = team
        game.ctf[new_name] = {'0': 0, '1': 0, '2': 0, '3': 0}
        game.weapons[new_name] = {
            'SHO': 0, 'GAU': 0, 'MAC': 0, 'GRE': 0,
            'ROC': 0, 'PLA': 0, 'RAI': 0, 'LIG': 0,
            'BFG': 0, 'TEL': 0, 'NAI': 0, 'CHA': 0
        }

        c_idx = this_line.find('ClientU')
        game.ptime[new_name] = totime(this_line[0:c_idx])
        # Keep track of player's current id
        game.pid[new_id] = new_name
    return game


def lineProcQuotes(this_line, game):
    '''Process quotes lines'''

    #  2:03 say: ^2ONAK: joder otra vez no
    name = this_line.split(':')[2]
    bs = this_line.split(':')[3][0:-1]
    game.quotes.add((name, bs))
    return game


def lineProcScores(this_line, game):
    '''Process scores lines'''

    #  5:40 score: 6  ping: 85  client: 2 Iagoi
    # 10:14 score: 12  ping: 62  client: 2 Iagoi
    regex = re.compile(
        r'(\s?\s?\s? \S*) '
        r'[\s][^\s]*[\s] (\S?\d*) '
        r'[\s]+[^\s]*[\s] (\d*) '
        r'[\s]+[^\s]*[\s] '
        r'(\d*) \s (.*)',
        re.VERBOSE
    )
    result = regex.search(this_line)

    [time, score, ping, client, nick] = [
        result.group(1), result.group(2),
        result.group(3), result.group(4),
        result.group(5)
    ]

    game.scores.append([time, score, ping, client, nick])
    game.players[nick] = (ping, game.pos)
    game.pos += 1  # Increase position for next player
    # Players are considered 'valid' if time played is greater than a
    # percentage of the time played by the 1st player who joined the game.
    # This: a) minimises the possibility of wrong item assignment due to
    # multiple connections and disconnections; b) results in fairer statistics
    if (game.time - game.ptime[nick]) > MINPLAY * (game.time -
                                                   min(game.ptime.values())):
        game.validp.append(nick)
    return game


def totime(string):
    '''Convert strings of the format mmm:ss to an int of seconds'''

    mins, secs = string.split(':')
    time = timedelta(minutes=int(mins), seconds=int(secs)).seconds
    return time


def csum(A):
    '''Column-wise addition of lists. Returns a list.'''

    # Check whether A is multidimensional
    if type(A[0]) is not list and type(A[0]) is not tuple:
        S = A
        return S
    # Check that A is not jagged
    for row in A:
        if len(row) != len(A[0]):
            print("Not square...")
    # Do the damn summation cause Python can't be bothered to do it alone
    S = []
    for i in range(len(A[0])):
        S.append(sum([row[i] for row in A]))
    return S


def get_quotes(cgames):
    '''Create non repeating list of quotes from list of games.'''

    if len(cgames) != 0:
        quotes_list = [cgames[i].quotes for i in range(len(cgames)) if
                       cgames[i].quotes != []]
        quotes_list = list(set([item for sublist in quotes_list for
                                item in sublist]))
    else:
        quotes_list = []
    return quotes_list


def allnames(cgames):
    '''Return names of all valid players in log.'''

    allnames = set()
    for game in cgames:
        allnames.update(game.validp)
    return allnames


def player_stats_total(cgames):
    '''Get accumulated stats per player for all players in log.'''

    all_players = []
    for name in allnames(cgames):
        win, time = 0, 0
        hand, ping, weapon_count, ctf_events = [], [], [], []
        frags, deaths, suics, wfrags = 0, 0, 0, 0
        awards_a, awards_c, awards_d, awards_e, awards_i = 0, 0, 0, 0, 0
        for i in range(len(cgames)):
            if name not in cgames[i].validp:  # ignore no valid players
                pass
            else:
                game_stats = player_stats(cgames, i, name)
                win = win + game_stats[1]
                time = time + game_stats[2]
                hand.append(int(game_stats[3]))
                ping.append(int(game_stats[4]))
                frags = frags + game_stats[5]
                deaths = deaths + game_stats[6]
                suics = suics + game_stats[7]
                wfrags = wfrags + game_stats[8]
                awards_a = awards_a + game_stats[9][0]
                awards_c = awards_c + game_stats[9][1]
                awards_d = awards_d + game_stats[9][2]
                awards_e = awards_e + game_stats[9][3]
                awards_i = awards_i + game_stats[9][4]
                weapon_count.append(game_stats[10])
                ctf_events.append(game_stats[11])
        if frags == 0:
            # Take rid of players with autodownload 'off' who
            # appear to join the server momentarily.
            pass
        else:
            one_player = {
                'name': name,  'games': len(hand),  'won': win,
                'time': time,  'hand': sum(hand)/len(hand),
                'ping': [min(ping), sum(ping)/len(ping), max(ping)],
                'frags': frags, 'deaths': deaths, 'suics': suics,
                'wfrags': wfrags, 'excellent': awards_e,
                'impressive': awards_i, 'defence': awards_d,
                'capture': awards_c,  'assist': awards_a,
                'weapons': csum(weapon_count),
                'ctf': csum(ctf_events)
            }
            all_players.append(one_player)
    return all_players


def player_stats(cgames, game_number, player_name):
    '''Gather the relevant numbers on a per-game, per-player basis.'''

    game = cgames[game_number]

    # Check player has actually played game and is tagged as valid
    if player_name not in game.validp:
        return 0

    time = game.time - game.ptime[player_name]
    ping = game.players[player_name][0]
    hand = game.handicap[player_name]

    if (game.gametype != '4') and (game.gametype != '3'):
        if game.players[player_name][1] == 1:
            win = 1
        else:
            win = 0
    else:
        # We 'try' it to avoid problems with spectators
        try:
            if (game.ctfscores[int(game.teams[player_name]) - 1] ==
                    max(game.ctfscores)):
                win = 1
            else:
                win = 0
        except(IndexError):
            win = 0

    awards = []
    awards.extend([n[1] for n in
                   sorted(game.awards[player_name].items())])
    wfrags = [n for n in game.killsp['<world>']].count(player_name)
    deaths = game.deathsp[player_name]
    suics = len([n for n in game.killsp[player_name]])
    frags = sum(game.weapons[player_name].values())
    weapon_count = []  # per weapon frags

    wlist = [
        'SHOTGUN', 'GAUNTLET', 'MACHINEGUN', 'GRENADE', 'GRENADE_SPLASH',
        'ROCKET', 'ROCKET_SPLASH', 'PLASMA', 'PLASMA_SPLASH', 'RAILGUN',
        'LIGHTNING', 'BFG10K', 'BFG10K_SPLASH', 'TELEFRAG', 'NAIL', 'CHAIN'
    ]
    for w in wlist:
        weapon_count.append(game.weapons[player_name][w[0:3]])

    if game.gametype == '4':
        flags_taken = game.ctf[player_name]['0']
        flags_retrd = game.ctf[player_name]['2']
        flag_fraggd = game.ctf[player_name]['3']
        ctf_events = (flags_taken, flags_retrd, flag_fraggd)
    else:
        ctf_events = (0, 0, 0)

    key = ['win', 'time', 'handicap', 'ping', 'frags', 'deaths', 'suics',
           'wfrags', 'awards', 'weapon count', 'ctf_events']

    return [key, win, time, hand, ping, frags, deaths, suics,
            wfrags, awards, weapon_count, ctf_events]


def results_ordered(R, option, maxnumber):
    '''Sort the dictionary-storing list R according to the key specified
    by option. The inexistent keys 'frag_death_ratio' and 'won_percentage'
    are added here for convenience. maxnumber limits the size of the
    output.'''

    if is_number(maxnumber) is False:
        print("\nINVALID MAXNUMBER VALUE IN results_ordered()")
        print("Check MAXPLAYERS option.\n")
        return
    if maxnumber > len(R):
        maxnumber = len(R)
    elif maxnumber <= 0:
        print("\nINVALID MAXNUMBER VALUE IN results_ordered()")
        print("Check MAXPLAYERS option.\n")
        return
    if option == 'frag_death_ratio':
        Rordered = sorted(R, key=lambda dic:
                          float(dic['frags'])/dic['deaths'], reverse=True)
    elif option == 'won_percentage':
        Rordered = sorted(R, key=lambda dic:
                          float(dic['won'])/dic['games'], reverse=True)
    elif option == 'frags_per_hour':
        Rordered = sorted(R, key=lambda dic:
                          float(dic['frags'])/dic['time'], reverse=True)
    elif option == 'name':
        Rordered = sorted(R, key=lambda dic:
                          float(dic['frags'])/dic['deaths'], reverse=False)
    elif option in R[0].keys():
        Rordered = sorted(R, key=lambda dic: dic[option], reverse=True)
    elif option not in R[0].keys():
        print("\nINVALID ORDERING OPTION IN results_ordered()")
        print("Check spelling?\n")
        return
    return Rordered[0:maxnumber]


def set_gametype(server):
    '''Stats only tested with game types 0 and 4, but we'll
       report the correct game type in any case.'''

    gametypes = {
        0: 'Death Match', 1: '1 vs 1', 2: 'Single Death Match',
        3: 'Team Death Match', 4: 'Capture the Flag', 5: 'One-Flag CTF',
        6: 'Overload', 7: 'Harvester', 8: 'Elimination',
        9: 'CTF Elimination', 10: 'Last Man Standing',
        11: 'Double Elimination', 12: 'Domination'
    }

    # If user specifies game type, report it regardless of what pyqscore parsed
    if GTYPE_OVERRIDE in '':
        server.gtype = gametypes[server.gtype]
    elif GTYPE_OVERRIDE in ['ctf', 'CTF']:
        server.gtype = 'Capture the Flag'
    elif GTYPE_OVERRIDE in ['dm', 'DM']:
        server.gtype = 'Death Match'
    elif GTYPE_OVERRIDE != '':
        server.gtype = GTYPE_OVERRIDE
    else:
        server.gtype = 'Unknown'
    return server


def apply_ban(R, BAN_LIST):
    ''''Possibly naive implementation of a black list of players.'''

    R_names = [player['name'] for player in R]
    ban_list_index = []

    for name in BAN_LIST:
        if name in R_names:
            ban_list_index.append(R_names.index(name))
    for i in sorted(ban_list_index, reverse=True):
        del(R[i])
    return R


def name_colour(nick):
    '''Parse Quake colour codes to HTML (uses pyqscores' CSS stylesheet).'''

    for n in range(8):
        code = '^' + str(n)
        html_code = '<SPAN class="c' + str(n) + '">'
        if nick.rfind(code) > -1:
            idx = nick.find(code)
            nick = nick[0:idx] + html_code + nick[idx+2:]
        else:
            nick = nick
    return nick


def is_number(s):
    '''Is 's' a number?'''

    try:
        int(s)
        return True
    except ValueError:
        return False


def make_main_table(R):
    '''List storing main data'''
    main_table_data = []
    for player in R:
        main_table_data.append([player['name'], player['games'], player['won'],
                                str(timedelta(seconds=player['time'])),
                                player['hand'], player['ping'][0],
                                player['ping'][1], player['ping'][2],
                                player['frags'], player['deaths'],
                                player['suics'], player['wfrags'],
                                player['excellent'], player['impressive']])
    return main_table_data


def make_weapons_table(R):
    '''List storing data for weapons table'''
    weapons_table = []
    for i in range(len(R)):
        weapons_table.append([R[i]['name']])
        weapons_table[i].extend(R[i]['weapons'][0:3])  # SHOTG, GAUNT, MGUN
        weapons_table[i].append(sum(R[i]['weapons'][3:5]))  # GRENADE
        weapons_table[i].append(sum(R[i]['weapons'][5:7]))  # ROCKET
        weapons_table[i].append(sum(R[i]['weapons'][7:9]))  # PLASMA
        weapons_table[i].extend(R[i]['weapons'][9:11])  # RAIL, LIGHTG
        weapons_table[i].extend(R[i]['weapons'][14:])  # NAILG, CHAING
        weapons_table[i].append(sum(R[i]['weapons'][11:13]))  # BFG
        weapons_table[i].extend(R[i]['weapons'][13:14])  # TELEFRAG

    for i in range(len(weapons_table)):
        for j in range(1, len(weapons_table[i])):
            value = (100. * weapons_table[i][j] / R[i]['frags'])
            weapons_table[i][j] = str(round(value, 2))
    return weapons_table


def make_stats_table(R):
    '''Another table with more numbers'''

    stats_table = []
    for i in range(len(R)):
        stats_table.append([
            R[i]['name'], 100. * R[i]['won'] / R[i]['games'],
            1. * R[i]['frags'] / (1 + R[i]['deaths']),
            3600. * R[i]['frags'] / R[i]['time'],
            1. * R[i]['frags'] / R[i]['games'],
            3600. * R[i]['deaths'] / R[i]['time'],
            1. * R[i]['deaths'] / R[i]['games'],
            3600. * (R[i]['suics'] + R[i]['wfrags']) / R[i]['time'],
            1. * (R[i]['suics'] + R[i]['wfrags']) / R[i]['games'],
            100. * R[i]['frags'] / (1 + R[i]['frags'] + R[i]['deaths'])
        ])

    for i in range(len(stats_table)):
        for j in range(1, len(stats_table[i])):
            stats_table[i][j] = str(round(stats_table[i][j], 2))
    return stats_table


def make_quotes_table(quotes_list):
    '''Random quotes'''

    quotes_table = []
    if len(quotes_list) > 0:
        for _ in range(NUMBER_OF_QUOTES):
            a = quotes_list[int(randint(0, len(quotes_list)-1))]
            quotes_table.append([name_colour(a[0]), a[1]])
    return quotes_table


def make_ctf_table(R):
    '''Table with CTF-related numbers'''

    ctf_table = []
    for i in range(len(R)):
        ctf_table.append([R[i]['name']])
        ctf_table[i].extend(R[i]['ctf'])
        ctf_table[i].extend([R[i]['defence'], R[i]['assist'], R[i]['capture']])
    return ctf_table


def logToData(log_file):
    '''Main wrapper to get the job done'''

    log = read_log(log_file)
    server, cgames = mainProcessing(log)
    quotes_list = get_quotes(cgames)

    if len(cgames) != 0:
        R = player_stats_total(cgames)
    else:
        print('\nNo valid games found in log. Play a bit more.\n')
        raise SystemExit()

    R = results_ordered(R, SORT_OPTION, MAXPLAYERS)
    server = set_gametype(server)  # update server with correct gametype

    R = apply_ban(R, BAN_LIST)
    for player in R:
        player['name'] = name_colour(player['name'])

    data = {
        'server': {
            'hostname': server.hostname,
            'gtype': server.gtype,
            'time': server.time,
            'frags': server.frags
        },
        'main': make_main_table(R),
        'stats': make_stats_table(R),
        'weapons': make_weapons_table(R),
        'quotes': make_quotes_table(quotes_list)
    }

    return data


def main():
    pass


if __name__ == '__main__':
    main()
