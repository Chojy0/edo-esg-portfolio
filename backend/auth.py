import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException, Request


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return salt + ':' + digest


def verify_password(password, encoded):
    salt, expected = encoded.split(':')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(request: Request, db):
    token = request.cookies.get('edo_session', '')
    user = db.execute('''SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
                         WHERE s.token=? AND s.expires>?''', (token_hash(token), int(time.time()))).fetchone()
    if not user:
        raise HTTPException(401, '로그인이 필요합니다.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, '요청 검증에 실패했습니다. 새로고침 후 다시 시도하세요.')
    return user


def admin(user):
    if user['role'] != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')


def supplier(user):
    if user['role'] != 'supplier':
        raise HTTPException(403, '협력사 계정으로 제출해 주세요.')


def assessment_access(db, user, assessment_id):
    row = db.execute('''SELECT a.*,c.name AS company_name,c.product FROM assessments a
                        JOIN companies c ON c.id=a.company_id WHERE a.id=?''', (assessment_id,)).fetchone()
    if not row or (user['role'] != 'admin' and row['company_id'] != user['company_id']):
        raise HTTPException(404, '진단을 찾을 수 없습니다.')
    return row


def public_user(user):
    return {key: user[key] for key in ('id','email','name','role','company_id')}
