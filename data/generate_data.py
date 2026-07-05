"""Generate a realistic synthetic grievance dataset for one Lok Sabha constituency."""
import random
import sqlite3
import datetime as dt
import os

random.seed(42)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "jansetu.db")

WARD_META = {
    "Rajpur North":    (26.492, 80.331, 182000, 14.2, 22, 3),
    "Rajpur South":    (26.421, 80.348, 165000, 18.5, 19, 2),
    "Ganga Vihar":     (26.478, 80.398, 121000, 12.1, 14, 2),
    "Shastri Nagar":   (26.455, 80.312, 143000, 22.8, 15, 1),
    "Ambedkar Colony": (26.437, 80.371, 98000,  41.5, 9,  1),
    "Indira Market":   (26.462, 80.352, 87000,  16.3, 8,  1),
    "Nehru Chowk":     (26.470, 80.338, 92000,  13.7, 10, 1),
    "Patel Nagar":     (26.446, 80.329, 134000, 15.9, 16, 2),
    "Kisan Basti":     (26.408, 80.392, 76000,  38.2, 6,  0),
    "Lal Bagh":        (26.483, 80.362, 110000, 11.4, 13, 2),
    "Station Road":    (26.459, 80.386, 95000,  17.6, 9,  1),
    "Civil Lines":     (26.474, 80.322, 88000,  8.9,  12, 2),
    "Ramganj":         (26.430, 80.316, 102000, 26.4, 10, 1),
    "Tilak Nagar":     (26.489, 80.379, 97000,  14.8, 11, 1),
    "Gandhi Maidan":   (26.451, 80.404, 84000,  19.2, 8,  1),
    "Subhash Colony":  (26.416, 80.336, 91000,  29.7, 8,  0),
}
WARDS = list(WARD_META.keys())

FUND_YEARS = [
    ("2024-25", 500.0, 445.0, 402.0, 61.0),
    ("2025-26", 500.0, 310.0, 218.0, 38.0),
    ("2026-27", 500.0, 95.0,  41.0,  6.5),
]

CATEGORIES = {
    "Water Supply":      {"dept": "Jal Board",             "base": 8,  "monsoon_mult": 1.6},
    "Drainage & Sewage": {"dept": "Municipal Corporation", "base": 7,  "monsoon_mult": 2.2},
    "Roads & Potholes":  {"dept": "PWD",                   "base": 9,  "monsoon_mult": 1.8},
    "Streetlights":      {"dept": "Electricity Board",     "base": 5,  "monsoon_mult": 1.0},
    "Garbage Collection":{"dept": "Municipal Corporation", "base": 10, "monsoon_mult": 1.2},
    "Electricity":       {"dept": "Electricity Board",     "base": 6,  "monsoon_mult": 1.3},
    "Public Health":     {"dept": "District Health Office","base": 4,  "monsoon_mult": 1.5},
    "Stray Animals":     {"dept": "Municipal Corporation", "base": 3,  "monsoon_mult": 1.0},
    "Encroachment":      {"dept": "Municipal Corporation", "base": 3,  "monsoon_mult": 1.0},
    "Public Transport":  {"dept": "Transport Dept",        "base": 3,  "monsoon_mult": 1.0},
}

DESCRIPTIONS = {
    "Water Supply": ["No water supply for the last {n} days in our lane","Contaminated water coming from the tap, children falling sick","Very low water pressure, only 30 minutes of supply daily","Water tanker has not visited despite repeated requests"],
    "Drainage & Sewage": ["Open drain overflowing near the primary school","Sewage water entering houses after rain","Drain cover broken, dangerous for children and elderly","Waterlogging on the main road for {n} days"],
    "Roads & Potholes": ["Huge pothole near the bus stop caused a two-wheeler accident","Road dug up for pipeline work and left unrepaired for {n} weeks","Entire stretch has no tar, becomes mud during rain","Speed breaker needed near the school gate"],
    "Streetlights": ["Streetlights not working for {n} days, unsafe for women at night","Entire lane dark after transformer repair, lights never restored","Streetlight pole leaning dangerously after storm","New colony has no streetlight poles installed at all"],
    "Garbage Collection": ["Garbage not collected for {n} days, foul smell in the area","Garbage van skips our lane regularly","Open dumping near the park, stray dogs increasing","Dustbins overflowing near the vegetable market"],
    "Electricity": ["Frequent power cuts of {n} hours daily","Low voltage damaging appliances","Hanging electric wires near the school, very dangerous","Transformer sparking at night"],
    "Public Health": ["Mosquito breeding in stagnant water, dengue cases rising","PHC has no doctor available in the evening","Fogging not done this season despite requests","Medicine shortage at the local health centre"],
    "Stray Animals": ["Stray cattle blocking the main road","Dog bite incidents increasing near the market","Monkey menace in residential colony"],
    "Encroachment": ["Footpath fully encroached, pedestrians forced onto the road","Illegal construction blocking the public lane","Vendors occupying the ambulance route near hospital"],
    "Public Transport": ["No bus service to the new colony","Bus stop shelter broken for {n} months","Auto stand causing jam at the main crossing"],
}

SOURCES = ["phone", "walk-in", "app-photo", "app-voice", "letter"]


def month_weight(d, cat):
    w = CATEGORIES[cat]["base"]
    if d.month in (6, 7, 8, 9):
        w *= CATEGORIES[cat]["monsoon_mult"]
    return w


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS grievances;
    CREATE TABLE grievances (
        id INTEGER PRIMARY KEY,
        created_date TEXT NOT NULL,
        ward TEXT NOT NULL,
        category TEXT NOT NULL,
        department TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL,
        source TEXT NOT NULL,
        status TEXT NOT NULL,
        resolved_date TEXT,
        upvotes INTEGER NOT NULL DEFAULT 0,
        lat REAL, lng REAL
    );
    CREATE INDEX idx_g_date ON grievances(created_date);
    CREATE INDEX idx_g_ward ON grievances(ward);
    CREATE INDEX idx_g_cat ON grievances(category);
    DROP TABLE IF EXISTS wards;
    CREATE TABLE wards (
        ward TEXT PRIMARY KEY,
        lat REAL NOT NULL, lng REAL NOT NULL,
        population INTEGER NOT NULL,
        sc_st_pct REAL NOT NULL,
        schools INTEGER NOT NULL,
        phcs INTEGER NOT NULL
    );
    DROP TABLE IF EXISTS mplads_funds;
    CREATE TABLE mplads_funds (
        year TEXT PRIMARY KEY,
        allocated_lakh REAL NOT NULL,
        sanctioned_lakh REAL NOT NULL,
        spent_lakh REAL NOT NULL,
        sc_st_spent_lakh REAL NOT NULL
    );
    """)
    c.executemany("INSERT INTO wards VALUES (?,?,?,?,?,?,?)", [(w, *m) for w, m in WARD_META.items()])
    c.executemany("INSERT INTO mplads_funds VALUES (?,?,?,?,?)", FUND_YEARS)

    start = dt.date.today() - dt.timedelta(days=548)
    end = dt.date.today()
    rows = []
    d = start
    while d <= end:
        for cat, meta in CATEGORIES.items():
            lam = month_weight(d, cat) / 7.0
            n = max(0, int(random.gauss(lam, lam * 0.6)))
            anomaly = cat == "Streetlights" and (end - d).days <= 21
            for _ in range(n + (random.randint(2, 4) if anomaly else 0)):
                ward = random.choice(["Shastri Nagar", "Kisan Basti"]) if anomaly and random.random() < 0.7 else random.choice(WARDS)
                desc = random.choice(DESCRIPTIONS[cat]).format(n=random.randint(2, 15))
                sev = random.choices(["low", "medium", "high"], weights=[4, 4, 2])[0]
                dept = meta["dept"]
                age = (end - d).days
                res_speed = {"PWD": 45, "Jal Board": 20, "Municipal Corporation": 15,
                             "Electricity Board": 10, "District Health Office": 25,
                             "Transport Dept": 60}[dept]
                if age > res_speed and random.random() < 0.75:
                    status = "resolved"
                    resolved = (d + dt.timedelta(days=max(1, int(random.gauss(res_speed, res_speed / 3))))).isoformat()
                elif random.random() < 0.4:
                    status, resolved = "in_progress", None
                else:
                    status, resolved = "open", None
                wlat, wlng = WARD_META[ward][0], WARD_META[ward][1]
                rows.append((d.isoformat(), ward, cat, dept, desc, sev,
                             random.choice(SOURCES), status, resolved,
                             random.randint(0, 40) if sev == "high" else random.randint(0, 8),
                             wlat + random.gauss(0, 0.006), wlng + random.gauss(0, 0.006)))
        d += dt.timedelta(days=1)

    c.executemany("""INSERT INTO grievances
        (created_date, ward, category, department, description, severity,
         source, status, resolved_date, upvotes, lat, lng)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    total = c.execute("SELECT COUNT(*) FROM grievances").fetchone()[0]
    print(f"jansetu.db created with {total} grievances at {os.path.abspath(DB_PATH)}")
    conn.close()


if __name__ == "__main__":
    main()
