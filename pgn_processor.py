"""PGN processor module for downloading PGN files from broadcasts."""

import io
import re

import chess.pgn
import requests

from cache import get_cached_tournament, cache_tournament

# ECO code to opening name lookup (from Lichess chess-openings dataset, CC0)
ECO_OPENINGS: dict[str, str] = {
    "A00": "Amar Opening",
    "A01": "Nimzo-Larsen Attack",
    "A02": "Bird Opening",
    "A03": "Bird Opening: Dutch Variation",
    "A04": "Colle System: Rhamphorhynchus Variation",
    "A05": "King's Indian Attack",
    "A06": "Nimzo-Larsen Attack: Classical Variation",
    "A07": "Hungarian Opening: Wiedenhagen-Beta Gambit",
    "A08": "King's Indian Attack: French Variation",
    "A09": "Réti Opening",
    "A10": "English Opening",
    "A11": "English Opening: Caro-Kann Defensive System",
    "A12": "Réti Opening: Anglo-Slav Variation",
    "A13": "English Opening: Agincourt Defense",
    "A14": "English Opening: Agincourt Defense, Keres Defense",
    "A15": "English Opening: Anglo-Indian Defense",
    "A16": "English Opening: Anglo-Grünfeld Defense",
    "A17": "English Opening: Anglo-Indian Defense",
    "A18": "English Opening: Mikenas-Carls Variation",
    "A19": "English Opening: Anglo-Indian Defense, Flohr-Mikenas-Carls Variation, Nei Gambit",
    "A20": "English Opening: Drill Variation",
    "A21": "English Opening: King's English Variation",
    "A22": "English Opening: Carls-Bremen System",
    "A23": "English Opening: King's English Variation, Two Knights Variation, Keres Variation",
    "A24": "English Opening: King's English Variation, Two Knights Variation, Fianchetto Line",
    "A25": "English Opening: Closed, Taimanov Variation",
    "A26": "English Opening: King's English Variation, Botvinnik System",
    "A27": "English Opening: King's English Variation, Three Knights System",
    "A28": "English Opening: Four Knights System, Nimzowitsch Variation",
    "A29": "English Opening: King's English Variation, Four Knights Variation, Fianchetto Line",
    "A30": "English Opening: Symmetrical Variation",
    "A31": "English Opening: Symmetrical Variation, Anti-Benoni Variation",
    "A32": "English Opening: Symmetrical Variation, Anti-Benoni Variation, Spielmann Defense",
    "A33": "English Opening: Symmetrical Variation, Anti-Benoni Variation, Geller Variation",
    "A34": "English Opening: Symmetrical Variation",
    "A35": "English Opening: Symmetrical Variation",
    "A36": "English Opening: Symmetrical Variation, Botvinnik System",
    "A37": "English Opening: Symmetrical Variation, Botvinnik System Reversed, with Nf3",
    "A38": "English Opening: Symmetrical Variation, Double Fianchetto",
    "A39": "English Opening: Symmetrical Variation, Mecking Variation",
    "A40": "Australian Defense",
    "A41": "Modern Defense",
    "A42": "Modern Defense: Averbakh System",
    "A43": "Benoni Defense: Benoni Gambit Accepted",
    "A44": "Benoni Defense: Old Benoni",
    "A45": "Amazon Attack: Siberian Attack",
    "A46": "Döry Defense",
    "A47": "Indian Defense: Schnepper Gambit",
    "A48": "East Indian Defense",
    "A49": "Indian Defense: Przepiorka Variation",
    "A50": "Indian Defense: Medusa Gambit",
    "A51": "Indian Defense: Budapest Defense",
    "A52": "Indian Defense: Budapest Defense",
    "A53": "Old Indian Defense",
    "A54": "Old Indian Defense: Duz-Khotimirsky Variation",
    "A55": "Old Indian Defense: Normal Variation",
    "A56": "Benoni Defense",
    "A57": "Benko Gambit",
    "A58": "Benko Gambit Accepted: Central Storming Variation",
    "A59": "Benko Gambit",
    "A60": "Benoni Defense: Modern Variation",
    "A61": "Benoni Defense",
    "A62": "Benoni Defense: Fianchetto Variation",
    "A63": "Benoni Defense: Fianchetto Variation, Hastings Defense",
    "A64": "Benoni Defense: Fianchetto Variation, Hastings Defense, Main Line",
    "A65": "Benoni Defense: King's Pawn Line",
    "A66": "Benoni Defense: Mikenas Variation",
    "A67": "Benoni Defense: Taimanov Variation",
    "A68": "Benoni Defense: Four Pawns Attack",
    "A69": "Benoni Defense: Four Pawns Attack, Main Line",
    "A70": "Benoni Defense: Classical Variation",
    "A71": "Benoni Defense: Classical Variation, Averbakh-Grivas Attack",
    "A72": "Benoni Defense: Classical Variation",
    "A73": "Benoni Defense: Classical Variation, Main Line",
    "A74": "Benoni Defense: Classical Variation, Full Line",
    "A75": "Benoni Defense: Classical Variation, Argentine Counterattack",
    "A76": "Benoni Defense: Classical Variation, Czerniak Defense",
    "A77": "Benoni Defense: Classical Variation, Czerniak Defense, Tal Line",
    "A78": "Benoni Defense: Classical Variation, Czerniak Defense",
    "A79": "Benoni Defense: Classical Variation, Czerniak Defense",
    "A80": "Dutch Defense",
    "A81": "Dutch Defense: Blackburne Variation",
    "A82": "Dutch Defense: Blackmar's Second Gambit",
    "A83": "Dutch Defense: Staunton Gambit",
    "A84": "Dutch Defense",
    "A85": "Dutch Defense: Queen's Knight Variation",
    "A86": "Dutch Defense: Fianchetto Variation",
    "A87": "Dutch Defense: Leningrad Variation",
    "A88": "Dutch Defense: Leningrad Variation, Warsaw Variation",
    "A89": "Dutch Defense: Leningrad Variation, Matulovic Variation",
    "A90": "Dutch Defense: Classical Variation",
    "A91": "Dutch Defense: Classical Variation",
    "A92": "Dutch Defense: Alekhine Variation",
    "A93": "Dutch Defense: Stonewall Variation, Botvinnik Variation",
    "A94": "Dutch Defense: Stonewall Variation",
    "A95": "Dutch Defense: Stonewall Variation",
    "A96": "Dutch Defense: Classical Variation",
    "A97": "Dutch Defense: Classical Variation, Ilyin-Zhenevsky Variation",
    "A98": "Dutch Defense: Classical Variation, Ilyin-Zhenevsky Variation, Alatortsev-Lisitsyn Line",
    "A99": "Dutch Defense: Classical Variation, Ilyin-Zhenevsky Variation, Modern Main Line",
    "B00": "Barnes Defense",
    "B01": "Scandinavian Defense",
    "B02": "Alekhine Defense",
    "B03": "Alekhine Defense",
    "B04": "Alekhine Defense: Modern Variation",
    "B05": "Alekhine Defense: Modern Variation, Alekhine Variation",
    "B06": "Modern Defense",
    "B07": "Czech Defense",
    "B08": "Pirc Defense: Classical Variation",
    "B09": "Pirc Defense: Austrian Attack",
    "B10": "Caro-Kann Defense",
    "B11": "Caro-Kann Defense: Two Knights Attack, Mindeno Variation",
    "B12": "Caro-Kann Defense",
    "B13": "Caro-Kann Defense: Exchange Variation",
    "B14": "Caro-Kann Defense: Panov Attack",
    "B15": "Caro-Kann Defense",
    "B16": "Caro-Kann Defense: Bronstein-Larsen Variation",
    "B17": "Caro-Kann Defense: Karpov Variation",
    "B18": "Caro-Kann Defense: Classical Variation",
    "B19": "Caro-Kann Defense: Classical Variation",
    "B20": "Sicilian Defense",
    "B21": "Bird Opening: Dutch Variation, Batavo Gambit",
    "B22": "Sicilian Defense: Alapin Variation",
    "B23": "Sicilian Defense: Closed",
    "B24": "Sicilian Defense: Closed",
    "B25": "Sicilian Defense: Closed",
    "B26": "Sicilian Defense: Closed",
    "B27": "Modern Defense: Pterodactyl Variation",
    "B28": "Sicilian Defense: O'Kelly Variation",
    "B29": "Sicilian Defense: Nimzowitsch Variation",
    "B30": "Sicilian Defense: Closed, Anti-Sveshnikov Variation",
    "B31": "Sicilian Defense: Nyezhmetdinov-Rossolimo Attack, Fianchetto Variation",
    "B32": "Sicilian Defense: Accelerated Dragon",
    "B33": "Sicilian Defense: Lasker-Pelikan Variation",
    "B34": "Sicilian Defense: Accelerated Dragon, Exchange Variation",
    "B35": "Sicilian Defense: Accelerated Dragon, Modern Bc4 Variation",
    "B36": "Sicilian Defense: Accelerated Dragon, Maróczy Bind",
    "B37": "Sicilian Defense: Accelerated Dragon, Maróczy Bind",
    "B38": "Sicilian Defense: Accelerated Dragon, Maróczy Bind",
    "B39": "Sicilian Defense: Accelerated Dragon, Maróczy Bind, Breyer Variation",
    "B40": "Sicilian Defense: Alapin Variation, Sherzer Variation",
    "B41": "Sicilian Defense: Kan Variation",
    "B42": "Sicilian Defense: Kan Variation, Gipslis Variation",
    "B43": "Sicilian Defense: Kan Variation, Knight Variation",
    "B44": "Sicilian Defense: Taimanov Variation",
    "B45": "Sicilian Defense: Four Knights Variation",
    "B46": "Sicilian Defense: Taimanov Variation",
    "B47": "Sicilian Defense: Taimanov Variation, Bastrikov Variation",
    "B48": "Sicilian Defense: Taimanov Variation, Bastrikov Variation, English Attack",
    "B49": "Sicilian Defense: Taimanov Variation, Bastrikov Variation",
    "B50": "Sicilian Defense",
    "B51": "Sicilian Defense: Moscow Variation",
    "B52": "Sicilian Defense: Moscow Variation, Haag Gambit",
    "B53": "Sicilian Defense: Chekhover Variation",
    "B54": "Sicilian Defense: Dragon Variation, Accelerated Dragon",
    "B55": "Sicilian Defense: Prins Variation, Venice Attack",
    "B56": "Sicilian Defense: Classical Variation",
    "B57": "Sicilian Defense: Classical Variation, Anti-Sozin Variation",
    "B58": "Sicilian Defense: Boleslavsky Variation",
    "B59": "Sicilian Defense: Boleslavsky Variation",
    "B60": "Sicilian Defense: Richter-Rauzer Variation",
    "B61": "Sicilian Defense: Richter-Rauzer Variation, Modern Variation",
    "B62": "Sicilian Defense: Richter-Rauzer Variation",
    "B63": "Sicilian Defense: Richter-Rauzer Variation, Classical Variation",
    "B64": "Sicilian Defense: Richter-Rauzer Variation, Classical Variation",
    "B65": "Sicilian Defense: Richter-Rauzer Variation, Classical Variation",
    "B66": "Sicilian Defense: Richter-Rauzer Variation, Neo-Modern Variation, Early Deviations",
    "B67": "Sicilian Defense: Richter-Rauzer Variation, Neo-Modern Variation",
    "B68": "Sicilian Defense: Richter-Rauzer Variation, Neo-Modern Variation",
    "B69": "Sicilian Defense: Richter-Rauzer Variation, Neo-Modern Variation, Nyezhmetdinov Attack",
    "B70": "Sicilian Defense: Dragon Variation",
    "B71": "Sicilian Defense: Dragon Variation, Levenfish Variation",
    "B72": "Sicilian Defense: Dragon Variation",
    "B73": "Sicilian Defense: Dragon Variation, Classical Variation",
    "B74": "Sicilian Defense: Dragon Variation, Classical Variation, Alekhine Line",
    "B75": "Sicilian Defense: Dragon Variation, Yugoslav Attack, Belezky Line",
    "B76": "Sicilian Defense: Dragon Variation, Yugoslav Attack",
    "B77": "Sicilian Defense: Dragon Variation, Yugoslav Attack",
    "B78": "Sicilian Defense: Dragon Variation, Yugoslav Attack",
    "B79": "Sicilian Defense: Dragon Variation, Yugoslav Attack",
    "B80": "Sicilian Defense: Scheveningen Variation",
    "B81": "Sicilian Defense: Scheveningen Variation, Keres Attack",
    "B82": "Sicilian Defense: Scheveningen Variation, Matanovic Attack",
    "B83": "Sicilian Defense: Scheveningen Variation, Classical Variation",
    "B84": "Sicilian Defense: Najdorf Variation, Scheveningen Variation",
    "B85": "Sicilian Defense: Scheveningen Variation, Classical Main Line",
    "B86": "Sicilian Defense: Sozin Attack",
    "B87": "Sicilian Defense: Sozin Attack, Flank Variation",
    "B88": "Sicilian Defense: Sozin Attack, Fischer Variation",
    "B89": "Sicilian Defense: Sozin Attack, Main Line",
    "B90": "Sicilian Defense: Najdorf Variation",
    "B91": "Sicilian Defense: Najdorf Variation, Zagreb Variation",
    "B92": "Sicilian Defense: Najdorf Variation, Opocensky Variation",
    "B93": "Sicilian Defense: Najdorf Variation, Amsterdam Variation",
    "B94": "Sicilian Defense: Najdorf Variation",
    "B95": "Sicilian Defense: Najdorf Variation",
    "B96": "Sicilian Defense: Najdorf Variation",
    "B97": "Sicilian Defense: Najdorf Variation, Poisoned Pawn Accepted",
    "B98": "Sicilian Defense: Najdorf Variation",
    "B99": "Sicilian Defense: Najdorf Variation, Main Line",
    "C00": "French Defense",
    "C01": "French Defense: Exchange Variation",
    "C02": "French Defense: Advance Variation",
    "C03": "French Defense: Tarrasch Variation",
    "C04": "French Defense: Tarrasch Variation, Guimard Defense, Main Line",
    "C05": "French Defense: Tarrasch Variation, Botvinnik Variation",
    "C06": "French Defense: Tarrasch Variation, Closed Variation, Main Line",
    "C07": "French Defense: Tarrasch Variation, Chistyakov Defense",
    "C08": "French Defense: Tarrasch Variation, Open System",
    "C09": "French Defense: Tarrasch Variation, Open System, Main Line",
    "C10": "French Defense: Hecht-Reefschläger Variation",
    "C11": "French Defense: Classical Variation",
    "C12": "French Defense: McCutcheon Variation",
    "C13": "French Defense: Alekhine-Chatard Attack",
    "C14": "French Defense: Classical Variation",
    "C15": "French Defense: McCutcheon Variation, Wolf Gambit",
    "C16": "French Defense: Winawer Variation, Advance Variation",
    "C17": "French Defense: Winawer Variation, Advance Variation",
    "C18": "French Defense: Winawer Variation, Advance Variation",
    "C19": "French Defense: Winawer Variation, Advance Variation, Smyslov Variation",
    "C20": "Barnes Opening: Walkerling",
    "C21": "Center Game",
    "C22": "Center Game: Berger Variation",
    "C23": "Bishop's Opening",
    "C24": "Bishop's Opening: Berlin Defense",
    "C25": "Vienna Gambit, with Max Lange Defense",
    "C26": "Bishop's Opening: Horwitz Gambit",
    "C27": "Bishop's Opening: Boden-Kieseritzky Gambit",
    "C28": "Bishop's Opening: Vienna Hybrid, Hromádka Variation",
    "C29": "Vienna Game: Heyde Variation",
    "C30": "King's Gambit",
    "C31": "King's Gambit Declined: Falkbeer Countergambit",
    "C32": "King's Gambit Declined: Falkbeer Countergambit, Alapin Variation",
    "C33": "King's Gambit Accepted",
    "C34": "King's Gambit Accepted: Becker Defense",
    "C35": "King's Gambit Accepted: Cunningham Defense",
    "C36": "King's Gambit Accepted: Abbazia Defense",
    "C37": "King's Gambit Accepted: Australian Gambit",
    "C38": "King's Gambit Accepted: Greco Gambit",
    "C39": "King's Gambit Accepted: Allgaier Gambit",
    "C40": "Elephant Gambit",
    "C41": "Philidor Defense",
    "C42": "Petrov's Defense",
    "C43": "Bishop's Opening: Urusov Gambit",
    "C44": "Dresden Opening: The Goblin",
    "C45": "Scotch Game",
    "C46": "Three Knights Opening",
    "C47": "Four Knights Game",
    "C48": "Four Knights Game: Spanish Variation",
    "C49": "Four Knights Game: Spanish Variation",
    "C50": "Four Knights Game: Italian Variation",
    "C51": "Italian Game: Evans Gambit",
    "C52": "Italian Game: Evans Gambit",
    "C53": "Italian Game: Bird's Attack",
    "C54": "Italian Game: Classical Variation",
    "C55": "Italian Game: Two Knights Defense",
    "C56": "Italian Game: Scotch Gambit",
    "C57": "Italian Game: Two Knights Defense, Fegatello Attack, Leonhardt Variation",
    "C58": "Italian Game: Two Knights Defense",
    "C59": "Italian Game: Two Knights Defense, Knorre Variation",
    "C60": "Ruy Lopez",
    "C61": "Ruy Lopez: Bird Variation",
    "C62": "Ruy Lopez: Steinitz Defense",
    "C63": "Ruy Lopez: Schliemann Defense",
    "C64": "Ruy Lopez: Classical Defense, Benelux Variation",
    "C65": "Ruy Lopez: Berlin Defense",
    "C66": "Ruy Lopez: Berlin Defense, Closed Bernstein Variation",
    "C67": "Ruy Lopez: Berlin Defense, Berlin Wall",
    "C68": "Ruy Lopez: Exchange Variation",
    "C69": "Ruy Lopez: Exchange Variation, Alapin Gambit",
    "C70": "Ruy Lopez: Bird's Defense Deferred",
    "C71": "Ruy Lopez: Morphy Defense, Modern Steinitz Defense",
    "C72": "Ruy Lopez: Closed, Kecskemet Variation",
    "C73": "Ruy Lopez: Morphy Defense, Modern Steinitz Defense",
    "C74": "Ruy Lopez: Morphy Defense, Modern Steinitz Defense",
    "C75": "Ruy Lopez: Morphy Defense, Modern Steinitz Defense",
    "C76": "Ruy Lopez: Morphy Defense, Modern Steinitz Defense, Fianchetto Variation",
    "C77": "Ruy Lopez: Morphy Defense, Anderssen Variation",
    "C78": "Ruy Lopez: Brix Variation",
    "C79": "Ruy Lopez: Morphy Defense, Steinitz Deferred",
    "C80": "Ruy Lopez: Morphy Defense, Tartakower Variation",
    "C81": "Ruy Lopez: Open, Howell Attack",
    "C82": "Ruy Lopez: Open",
    "C83": "Ruy Lopez: Open, Breslau Variation",
    "C84": "Ruy Lopez: Closed",
    "C85": "Ruy Lopez: Closed, Delayed Exchange",
    "C86": "Ruy Lopez: Closed, Worrall Attack",
    "C87": "Ruy Lopez: Closed, Averbakh Variation",
    "C88": "Ruy Lopez: Closed",
    "C89": "Ruy Lopez: Marshall Attack",
    "C90": "Ruy Lopez: Closed",
    "C91": "Ruy Lopez: Closed, Bogoljubow Variation",
    "C92": "Ruy Lopez: Closed",
    "C93": "Ruy Lopez: Closed, Smyslov Defense",
    "C94": "Ruy Lopez: Closed, Breyer Defense",
    "C95": "Ruy Lopez: Closed, Breyer",
    "C96": "Ruy Lopez: Closed, Borisenko Variation",
    "C97": "Ruy Lopez: Closed, Chigorin Defense",
    "C98": "Ruy Lopez: Closed, Chigorin Defense",
    "C99": "Ruy Lopez: Closed, Chigorin Defense, Panov System",
    "D00": "Amazon Attack",
    "D01": "Rapport-Jobava System",
    "D02": "London System: Poisoned Pawn Variation",
    "D03": "Queen's Pawn Game: Torre Attack",
    "D04": "Queen's Pawn Game: Colle System",
    "D05": "Queen's Pawn Game: Colle System",
    "D06": "Queen's Gambit",
    "D07": "Queen's Gambit Declined: Chigorin Defense",
    "D08": "Queen's Gambit Declined: Albin Countergambit",
    "D09": "Queen's Gambit Declined: Albin Countergambit, Fianchetto Variation",
    "D10": "Slav Defense",
    "D11": "Slav Defense: Bonet Gambit",
    "D12": "Slav Defense: Quiet Variation, Amsterdam Variation",
    "D13": "Slav Defense: Exchange Variation",
    "D14": "Slav Defense: Exchange Variation, Symmetrical Line",
    "D15": "Slav Defense: Alekhine Variation",
    "D16": "Slav Defense: Alapin Variation",
    "D17": "Slav Defense: Czech Variation",
    "D18": "Slav Defense: Czech Variation, Classical System",
    "D19": "Slav Defense: Czech Variation, Classical System, Main Line",
    "D20": "Queen's Gambit Accepted",
    "D21": "Queen's Gambit Accepted: Alekhine Defense, Borisenko-Furman Variation",
    "D22": "Queen's Gambit Accepted: Alekhine Defense",
    "D23": "Queen's Gambit Accepted",
    "D24": "Queen's Gambit Accepted",
    "D25": "Queen's Gambit Accepted: Janowski-Larsen Variation",
    "D26": "Queen's Gambit Accepted: Classical Defense",
    "D27": "Queen's Gambit Accepted: Classical Defense, Main Line",
    "D28": "Queen's Gambit Accepted: Classical Defense, Alekhine System",
    "D29": "Queen's Gambit Accepted: Classical Defense, Alekhine System, Main Line",
    "D30": "Queen's Gambit Declined",
    "D31": "Queen's Gambit Declined: Alapin Variation",
    "D32": "Queen's Gambit Declined: Tarrasch Defense",
    "D33": "Tarrasch Defense: Dubov Tarrasch",
    "D34": "Queen's Gambit Declined: Tarrasch Defense, Stoltz Variation",
    "D35": "Queen's Gambit Declined: Exchange Variation",
    "D36": "Queen's Gambit Declined: Exchange Variation, Reshevsky Variation",
    "D37": "Queen's Gambit Declined: Barmen Variation",
    "D38": "Queen's Gambit Declined: Ragozin Defense",
    "D39": "Queen's Gambit Declined: Ragozin Defense, Vienna Variation",
    "D40": "Queen's Gambit Declined: Semi-Tarrasch Defense",
    "D41": "Queen's Gambit Declined: Semi-Tarrasch Defense",
    "D42": "Queen's Gambit Declined: Semi-Tarrasch Defense, Main Line",
    "D43": "Semi-Slav Defense",
    "D44": "Semi-Slav Defense Accepted",
    "D45": "Semi-Slav Defense: Accelerated Meran Variation",
    "D46": "Semi-Slav Defense: Bogoljubow Variation",
    "D47": "Semi-Slav Defense: Meran Variation",
    "D48": "Semi-Slav Defense: Meran Variation",
    "D49": "Semi-Slav Defense: Meran Variation, Blumenfeld Variation",
    "D50": "Queen's Gambit Declined: Been-Koomen Variation",
    "D51": "Queen's Gambit Declined: Alekhine Variation",
    "D52": "Queen's Gambit Declined",
    "D53": "Queen's Gambit Declined",
    "D54": "Queen's Gambit Declined: Neo-Orthodox Variation",
    "D55": "Queen's Gambit Declined: Anti-Tartakower Variation",
    "D56": "Queen's Gambit Declined: Lasker Defense",
    "D57": "Queen's Gambit Declined: Lasker Defense, Bernstein Variation",
    "D58": "Queen's Gambit Declined: Tartakower Defense",
    "D59": "Queen's Gambit Declined: Tartakower Defense",
    "D60": "Queen's Gambit Declined: Orthodox Defense",
    "D61": "Queen's Gambit Declined: Orthodox Defense, Rubinstein Variation",
    "D62": "Queen's Gambit Declined: Orthodox Defense, Rubinstein Variation, Flohr Line",
    "D63": "Queen's Gambit Declined: Orthodox Defense, Capablanca Variation",
    "D64": "Queen's Gambit Declined: Orthodox Defense, Rubinstein Attack",
    "D65": "Queen's Gambit Declined: Orthodox Defense, Rubinstein Attack",
    "D66": "Queen's Gambit Declined: Orthodox Defense, Bd3 Line",
    "D67": "Queen's Gambit Declined: Orthodox Defense, Alekhine Variation",
    "D68": "Queen's Gambit Declined: Orthodox Defense, Classical Variation",
    "D69": "Queen's Gambit Declined: Orthodox Defense, Classical Variation",
    "D70": "Neo-Grünfeld Defense: Goglidze Attack",
    "D71": "Neo-Grünfeld Defense: Exchange Variation",
    "D74": "Neo-Grünfeld Defense: Delayed Exchange Variation",
    "D75": "Neo-Grünfeld Defense: Delayed Exchange Variation",
    "D76": "Neo-Grünfeld Defense: Delayed Exchange Variation",
    "D77": "Neo-Grünfeld Defense: Classical Variation",
    "D78": "Neo-Grünfeld Defense: Classical Variation, Original Defense",
    "D79": "Neo-Grünfeld Defense: Ultra-Delayed Exchange Variation",
    "D80": "Grünfeld Defense",
    "D81": "Grünfeld Defense: Russian Variation, Accelerated Variation",
    "D82": "Grünfeld Defense: Brinckmann Attack",
    "D83": "Grünfeld Defense: Brinckmann Attack, Grünfeld Gambit",
    "D84": "Grünfeld Defense: Brinckmann Attack, Grünfeld Gambit Accepted",
    "D85": "Grünfeld Defense: Exchange Variation",
    "D86": "Grünfeld Defense: Exchange Variation, Classical Variation",
    "D87": "Grünfeld Defense: Exchange Variation, Seville Variation",
    "D88": "Grünfeld Defense: Exchange Variation, Spassky Variation",
    "D89": "Grünfeld Defense: Exchange Variation, Sokolsky Variation",
    "D90": "Grünfeld Defense: Flohr Variation",
    "D91": "Grünfeld Defense: Three Knights Variation, Petrosian System",
    "D92": "Grünfeld Defense: Three Knights Variation, Hungarian Attack",
    "D93": "Grünfeld Defense: Three Knights Variation, Hungarian Variation",
    "D94": "Grünfeld Defense: Flohr Defense",
    "D95": "Grünfeld Defense: Botvinnik Variation",
    "D96": "Grünfeld Defense: Russian Variation",
    "D97": "Grünfeld Defense: Russian Variation",
    "D98": "Grünfeld Defense: Russian Variation, Keres Variation",
    "D99": "Grünfeld Defense: Russian Variation, Smyslov Variation",
    "E00": "Catalan Opening",
    "E01": "Catalan Opening: Closed",
    "E02": "Catalan Opening: Open Defense",
    "E03": "Catalan Opening: Open Defense",
    "E04": "Catalan Opening: Open Defense",
    "E05": "Catalan Opening: Open Defense, Classical Line",
    "E06": "Catalan Opening: Closed",
    "E07": "Catalan Opening: Closed",
    "E08": "Catalan Opening: Closed",
    "E09": "Catalan Opening: Closed Variation, Rabinovich Variation",
    "E10": "Blumenfeld Countergambit",
    "E11": "Bogo-Indian Defense",
    "E12": "Queen's Indian Defense",
    "E13": "Queen's Indian Defense: Kasparov Variation",
    "E14": "Queen's Indian Defense, with e3",
    "E15": "Queen's Indian Defense: Buerger Variation",
    "E16": "Queen's Indian Defense: Capablanca Variation",
    "E17": "Queen's Indian Defense: Anti-Queen's Indian System",
    "E18": "Queen's Indian Defense: Classical Variation, Tiviakov Defense",
    "E19": "Queen's Indian Defense: Classical Variation, Traditional Variation, Main Line",
    "E20": "Nimzo-Indian Defense",
    "E21": "Nimzo-Indian Defense: Three Knights Variation",
    "E22": "Nimzo-Indian Defense: Spielmann Variation",
    "E23": "Nimzo-Indian Defense: Spielmann Variation, Carlsbad Variation",
    "E24": "Nimzo-Indian Defense: Sämisch Variation",
    "E25": "Nimzo-Indian Defense: Sämisch Variation",
    "E26": "Nimzo-Indian Defense: Sämisch Variation",
    "E27": "Nimzo-Indian Defense: Sämisch Variation",
    "E28": "Nimzo-Indian Defense: Sämisch Variation",
    "E29": "Nimzo-Indian Defense: Sämisch Variation",
    "E30": "Nimzo-Indian Defense: Leningrad Variation",
    "E31": "Nimzo-Indian Defense: Leningrad Variation, Benoni Defense",
    "E32": "Nimzo-Indian Defense: Classical Variation",
    "E33": "Nimzo-Indian Defense: Classical Variation, Milner-Barry Variation",
    "E34": "Nimzo-Indian Defense: Classical Variation, Belyavsky Gambit",
    "E35": "Nimzo-Indian Defense: Classical Variation, Noa Variation",
    "E36": "Nimzo-Indian Defense: Classical Variation, Noa Variation",
    "E37": "Nimzo-Indian Defense: Classical Variation, Modern Variation",
    "E38": "Nimzo-Indian Defense: Classical Variation, Berlin Variation",
    "E39": "Nimzo-Indian Defense: Classical Variation, Berlin Variation, Macieja System",
    "E40": "Nimzo-Indian Defense: Rubinstein System",
    "E41": "Nimzo-Indian Defense: Rubinstein System",
    "E42": "Nimzo-Indian Defense: Rubinstein System, Rubinstein Variation",
    "E43": "Nimzo-Indian Defense: St. Petersburg Variation",
    "E44": "Nimzo-Indian Defense: St. Petersburg Variation",
    "E45": "Nimzo-Indian Defense: St. Petersburg Variation, Fischer Variation",
    "E46": "Nimzo-Indian Defense: Normal Variation",
    "E47": "Nimzo-Indian Defense: Normal Variation",
    "E48": "Nimzo-Indian Defense: Normal Variation, Classical Defense",
    "E49": "Nimzo-Indian Defense: Normal Variation, Botvinnik System",
    "E50": "Nimzo-Indian Defense",
    "E51": "Nimzo-Indian Defense: Normal Variation, Ragozin Variation",
    "E52": "Nimzo-Indian Defense: Normal Variation, Schlechter Defense",
    "E53": "Nimzo-Indian Defense: Normal Variation, Gligoric System",
    "E54": "Nimzo-Indian Defense: Normal Variation, Gligoric System, Exchange Variation",
    "E55": "Nimzo-Indian Defense: Normal Variation, Gligoric System, Bronstein Variation",
    "E56": "Nimzo-Indian Defense: Normal Variation, Gligoric System, Bernstein Defense",
    "E57": "Nimzo-Indian Defense: Normal Variation, Gligoric System, Bernstein Defense",
    "E58": "Nimzo-Indian Defense: Normal Variation, Bernstein Defense, Exchange Line",
    "E59": "Nimzo-Indian Defense: Normal Variation, Bernstein Defense",
    "E60": "Grünfeld Defense: Counterthrust Variation",
    "E61": "King's Indian Defense",
    "E62": "King's Indian Defense: Fianchetto Variation, Carlsbad Variation",
    "E63": "King's Indian Defense: Fianchetto Variation, Panno Variation",
    "E64": "King's Indian Defense: Fianchetto Variation, Double Fianchetto Attack",
    "E65": "King's Indian Defense: Fianchetto Variation, Yugoslav Variation",
    "E66": "King's Indian Defense: Fianchetto Variation, Yugoslav Variation, Advance Line",
    "E67": "King's Indian Defense: Fianchetto Variation, Classical Fianchetto",
    "E68": "King's Indian Defense: Fianchetto Variation, Classical Variation",
    "E69": "King's Indian Defense: Fianchetto Variation, Classical Main Line",
    "E70": "King's Indian Defense: Accelerated Averbakh Variation",
    "E71": "King's Indian Defense: Karpov System",
    "E72": "King's Indian Defense: Normal Variation, Deferred Fianchetto",
    "E73": "King's Indian Defense: Averbakh Variation",
    "E74": "King's Indian Defense: Averbakh Variation, Benoni Defense",
    "E75": "King's Indian Defense: Averbakh Variation, Main Line",
    "E76": "King's Indian Defense: Four Pawns Attack",
    "E77": "King's Indian Defense: Four Pawns Attack",
    "E78": "King's Indian Defense: Four Pawns Attack, Fluid Attack",
    "E79": "King's Indian Defense: Four Pawns Attack, Exchange Variation",
    "E80": "King's Indian Defense: Sämisch Variation",
    "E81": "King's Indian Defense: Steiner Attack",
    "E82": "King's Indian Defense: Sämisch Variation, Double Fianchetto",
    "E83": "King's Indian Defense: Sämisch Variation, Panno Formation",
    "E84": "King's Indian Defense: Sämisch Variation, Panno Main Line",
    "E85": "King's Indian Defense: Sämisch Variation, Orthodox Variation",
    "E86": "King's Indian Defense: Sämisch Variation",
    "E87": "King's Indian Defense: Sämisch Variation, Bronstein Defense",
    "E88": "King's Indian Defense: Sämisch Variation, Closed Variation",
    "E89": "King's Indian Defense: Sämisch Variation, Closed Variation, Main Line",
    "E90": "King's Indian Defense: Larsen Variation",
    "E91": "King's Indian Defense: Kazakh Variation",
    "E92": "King's Indian Defense: Exchange Variation",
    "E93": "King's Indian Defense: Petrosian Variation, Keres Defense",
    "E94": "King's Indian Defense: Orthodox Variation",
    "E95": "King's Indian Defense: Orthodox Variation",
    "E96": "King's Indian Defense: Orthodox Variation, Positional Defense, Main Line",
    "E97": "King's Indian Defense: Orthodox Variation, Aronin-Taimanov Defense",
    "E98": "King's Indian Defense: Orthodox Variation, Classical System",
    "E99": "King's Indian Defense: Orthodox Variation, Classical System, Benko Attack",
}




def download_broadcast_pgn(broadcast_url: str) -> str:
    """Download PGN data from a Lichess broadcast URL.

    Checks cache first before making HTTP request. Caches successful results.

    Args:
        broadcast_url: A URL in the format https://lichess.org/broadcast/tournament-slug/round-slug/id
                       or https://lichess.org/broadcast/tournament-slug/id

    Returns:
        Raw PGN text from the broadcast, or empty string on error.
    """
    try:
        # Fetch the broadcast page to find the actual tournament ID
        page_response = requests.get(broadcast_url, timeout=30)
        page_response.raise_for_status()

        # The tournament ID is inside the page-init-data JSON in the HTML
        match = re.search(r'"tour":\{"id":"([^"]+)"', page_response.text)
        if match:
            tournament_id = match.group(1)
        else:
            # Fallback: use last path component
            url_parts = broadcast_url.rstrip("/").split("/")
            tournament_id = url_parts[-1]

        # Check cache first
        cached = get_cached_tournament(tournament_id)
        if cached is not None:
            return cached

        # Construct API URL and fetch
        api_url = f"https://lichess.org/api/broadcast/{tournament_id}.pgn"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        pgn_text = response.text

        # Cache the result
        if pgn_text:
            cache_tournament(tournament_id, pgn_text, broadcast_url)

        return pgn_text
    except requests.RequestException:
        return ""


def filter_games_by_fide(pgn_text: str, fide_id: str, player_name: str = "") -> str:
    """Filter PGN games by FIDE ID or player name.

    Args:
        pgn_text: Raw PGN text containing one or more games.
        fide_id: FIDE ID to filter for (as string).
        player_name: Optional player name slug (e.g. "Carlsen_Magnus") for fallback.

    Returns:
        Filtered PGN text containing matching games.
    """
    if not pgn_text:
        return ""

    matching_games = []
    pgn_stream = io.StringIO(pgn_text)

    # Prepare player name variations for matching
    name_variants = []
    if player_name:
        name_variants.append(player_name.lower())
        name_variants.append(player_name.replace("_", " ").lower())
        # Try "Lastname, Firstname" format if slug is "Lastname_Firstname"
        if "_" in player_name:
            parts = player_name.split("_")
            name_variants.append(f"{parts[0]}, {parts[1]}".lower())

    while True:
        try:
            game = chess.pgn.read_game(pgn_stream)
            if game is None:
                break

            # 1. Check FIDE IDs from headers (priority)
            white_fide = game.headers.get("WhiteFideId", "")
            black_fide = game.headers.get("BlackFideId", "")

            is_match = white_fide == fide_id or black_fide == fide_id

            # 2. Fallback: Check player names if no FIDE ID match
            if not is_match and name_variants:
                white_name = game.headers.get("White", "").lower()
                black_name = game.headers.get("Black", "").lower()

                for variant in name_variants:
                    if variant in white_name or variant in black_name:
                        is_match = True
                        break

            if is_match:
                # Export the matching game to PGN string
                exporter = chess.pgn.StringExporter()
                pgn_output = game.accept(exporter)
                # Add Sjakkfangst comment after headers (before movetext)
                # Headers end at first blank line; insert comment there
                lines = pgn_output.split("\n")
                header_end = 0
                for i, line in enumerate(lines):
                    if line.strip() == "":
                        header_end = i
                        break
                lines.insert(header_end + 1, "{Downloaded with Sjakkfangst}")
                matching_games.append("\n".join(lines))
        except Exception:
            continue

    return "\n\n".join(matching_games)


def collect_opening_stats(pgn_text, fide_id):
    """Collect opening statistics for a given FIDE player.

    Returns a list of dicts with keys:
        opening, eco, games, wins, draws, losses, win_pct, avg_elo, date_from, date_to
    Sorted by games descending.
    """
    if not pgn_text:
        return []

    stats = {}
    stream = io.StringIO(pgn_text)

    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        headers = game.headers

        white_fide = headers.get("WhiteFideId", "")
        black_fide = headers.get("BlackFideId", "")

        if white_fide != fide_id and black_fide != fide_id:
            continue

        is_white = white_fide == fide_id
        result = headers.get("Result", "*")

        # Determine outcome for the player
        if is_white:
            if result == "1-0":
                outcome = "W"
            elif result == "0-1":
                outcome = "L"
            elif result == "1/2-1/2":
                outcome = "D"
            else:
                outcome = "D"
        else:
            if result == "0-1":
                outcome = "W"
            elif result == "1-0":
                outcome = "L"
            elif result == "1/2-1/2":
                outcome = "D"
            else:
                outcome = "D"

        # Get opening name: always use ECO lookup, ignore Lichess Opening header
        eco_code = headers.get("ECO", "")
        if eco_code:
            opening = ECO_OPENINGS.get(eco_code, f"ECO {eco_code}")
        else:
            opening = headers.get("Opening", "Unknown")

        # Get opponent Elo
        opponent_elo = None
        try:
            elo_str = headers.get("BlackElo" if is_white else "WhiteElo", "")
            opponent_elo = int(elo_str) if elo_str and elo_str.isdigit() else None
        except ValueError:
            opponent_elo = None

        # Get date
        date_str = headers.get("Date", "????.??.??")

        key = (opening, eco_code)
        if key not in stats:
            stats[key] = {
                "opening": opening,
                "eco": eco_code,
                "games": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "elos": [],
                "dates": [],
            }

        entry = stats[key]
        entry["games"] += 1
        if outcome == "W":
            entry["wins"] += 1
        elif outcome == "D":
            entry["draws"] += 1
        else:
            entry["losses"] += 1
        if opponent_elo is not None:
            entry["elos"].append(opponent_elo)
        entry["dates"].append(date_str)

    # Build final list
    result_list = []
    for entry in stats.values():
        avg_elo = (
            round(sum(entry["elos"]) / len(entry["elos"]))
            if entry["elos"]
            else None
        )
        win_pct = round(entry["wins"] / entry["games"] * 100) if entry["games"] else 0

        result_list.append(
            {
                "opening": entry["opening"],
                "eco": entry["eco"],
                "games": entry["games"],
                "wins": entry["wins"],
                "draws": entry["draws"],
                "losses": entry["losses"],
                "win_pct": win_pct,
                "avg_elo": avg_elo,
                "date_from": min(entry["dates"]) if entry["dates"] else "",
                "date_to": max(entry["dates"]) if entry["dates"] else "",
            }
        )

    result_list.sort(key=lambda x: x["games"], reverse=True)
    return result_list
