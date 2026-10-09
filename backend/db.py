import sqlite3
from contextlib import contextmanager

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, name TEXT NOT NULL, product TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','supplier')), company_id INTEGER REFERENCES companies(id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT NOT NULL, attempted INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS login_attempts_time ON login_attempts(attempted);
CREATE TABLE IF NOT EXISTS assessments(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), title TEXT NOT NULL, deadline TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'requested', version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS answers(assessment_id INTEGER NOT NULL REFERENCES assessments(id), question_id TEXT NOT NULL, answer TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', PRIMARY KEY(assessment_id,question_id));
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessments(id), kind TEXT NOT NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE, media_type TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '', current INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS evidence_assessment ON evidence(assessment_id,current);
CREATE TABLE IF NOT EXISTS reports(assessment_id INTEGER PRIMARY KEY REFERENCES assessments(id), body TEXT NOT NULL, source TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, assessment_id INTEGER REFERENCES assessments(id), read INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,id);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), assessment_id INTEGER REFERENCES assessments(id), action TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS document_processing(evidence_id INTEGER PRIMARY KEY REFERENCES evidence(id), pages TEXT NOT NULL, checks TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS document_chunks(id INTEGER PRIMARY KEY, evidence_id INTEGER NOT NULL REFERENCES evidence(id), page INTEGER NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_evidence ON document_chunks(evidence_id);
PRAGMA user_version=2;
'''

@contextmanager
def connect(settings):
    db = sqlite3.connect(settings.data_dir / 'edo.sqlite3', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init_db(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / 'uploads').mkdir(exist_ok=True)
    with connect(settings) as db:
        db.executescript(SCHEMA)

def notify(db, assessment, message, role):
    if role == 'admin':
        users = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
    else:
        users = db.execute("SELECT id FROM users WHERE role='supplier' AND company_id=?", (assessment['company_id'],)).fetchall()
    db.executemany('INSERT INTO notifications(user_id,message,assessment_id) VALUES(?,?,?)', [(u['id'], message, assessment['id']) for u in users])

def audit(db, user, assessment_id, action):
    db.execute('INSERT INTO audit(user_id,assessment_id,action) VALUES(?,?,?)', (user['id'], assessment_id, action))
