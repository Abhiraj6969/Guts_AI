"""tekken8_knowledge.py - what Guts knows about Tekken 8.

Everything here was checked against public guides (Oct 2026). Move lists and frame data are NOT stored here:
for those Guts must say he is not sure (or use the research tool), because wrong move data is worse than none.
Update ROSTER when a new fighter is released.
"""

BASE_ROSTER = [
    "Claudio", "Zafina", "Paul", "Raven", "Victor", "Reina", "Azucena", "Shaheen", "Law", "Leroy", "Leo",
    "Panda", "Asuka", "Lee", "Xiaoyu", "Jin", "Kazuya", "Nina", "Hwoarang", "Feng", "Yoshimitsu", "Kuma",
    "Lili", "Alisa", "Lars", "Jun", "Devil Jin", "Jack-8", "King", "Steve", "Dragunov", "Bryan",
]
DLC_ROSTER = [
    "Eddy", "Lidia", "Heihachi", "Clive",                        # season 1
    "Anna", "Fahkumram", "Armor King", "Miary Zo",               # season 2
    "Kunimitsu", "Bob", "Roger", "Yujiro Hanma",                 # season 3 (Roger / Yujiro may not be out yet)
]
ROSTER = BASE_ROSTER + DLC_ROSTER

MECHANICS = (
    "HUD: each player has a YELLOW health bar at the top and a BLUE Heat bar just under it; the fighters' names "
    "are written near the bars. "
    "HEAT: Heat Burst (buttons 2+3, or R1/RB on a pad) starts Heat state for about 10 seconds; a "
    "Heat Engager (different for every character) only starts Heat when it HITS, dashes in for a follow-up combo "
    "and gives about 15 seconds. In Heat the character is stronger (more damage, extra combos) and a blue glow shows. "
    "Heat Dash spends Heat to dash in and extend a combo. Heat Smash spends the rest of the Heat for a big "
    "damage move and ends Heat. While Heat is active, blocked attacks turn the opponent's health into "
    "white recoverable health (chip). Heat only comes back at the next round. "
    "RAGE: at low health the character goes into Rage; Rage Art is a cinematic super move that ends Rage; lower "
    "health gives bigger Rage Art damage. Rage Drive was removed in Tekken 8. "
    "POWER CRUSH moves absorb highs and mids but lose to lows. "
    "Basics: highs are ducked, mids need standing block, lows need crouch block; throws are broken by pressing "
    "the same button; walls give wall carry and wall splat combos."
)

STYLE = (
    "You are Boss's best friend watching Tekken 8 together and commenting live like a friend, not a robot. "
    "One short punchy Hinglish line, maximum 12 words, with real reactions: hype, shock, playful roast of both "
    "sides, celebration of comebacks. Vary the lines, never repeat the same joke. "
    "Talk ONLY about the game, and ONLY when a [GAME EVENT] message arrives or Boss asks you something. "
    "Stay silent on menus and loading screens and do not start any other conversation while the game is on. "
    "Use ONLY the facts in the event message: names, health numbers, rounds, Heat. Never invent move names, "
    "combos or frame data; if Boss asks for a move or frame data you are not sure of, say you are not sure. "
    "When Boss asks which character, who is winning or how much health, call game_buddy with status and answer "
    "from it, never guess a character from its looks. "
    "Do not read the tag [GAME EVENT] aloud."
)


def game_prompt() -> str:
    return ("TEKKEN 8. To start the game call open_tekken8. To turn on the friend commentary call game_buddy with "
            "on (add boss_side right if Boss plays on the right). Turn it off with game_buddy off. After you call "
            "it, say at most one word. " + STYLE + " Roster: " + ", ".join(ROSTER) + ". " + MECHANICS + " ")
