"""Local account bootstrap; never seeds credentials at server startup."""
import argparse
import getpass
from .config import Settings
from .db import init_db, connect
from .auth import hash_password


def main():
    parser=argparse.ArgumentParser(description='EDO 계정 초기화')
    parser.add_argument('command',choices=['create-admin','seed-demo'])
    parser.add_argument('--email',default='admin@example.test')
    args=parser.parse_args(); settings=Settings(); init_db(settings)
    password=getpass.getpass('비밀번호 (12자 이상, 화면에 표시되지 않음): ')
    if len(password)<12:parser.error('12자 이상의 비밀번호가 필요합니다.')
    if getpass.getpass('비밀번호 확인: ')!=password:parser.error('비밀번호가 일치하지 않습니다.')
    with connect(settings) as db:
        if db.execute('SELECT 1 FROM users WHERE email=?',(args.email.lower(),)).fetchone():parser.error('계정이 이미 존재합니다. 데이터를 변경하지 않았습니다.')
        db.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,'admin')",(args.email.lower(),'관리자',hash_password(password)))
        if args.command=='seed-demo':
            if db.execute("SELECT 1 FROM users WHERE email='supplier@example.test'").fetchone():parser.error('데모 협력사 계정이 이미 있습니다.')
            id=db.execute("INSERT INTO companies(name,product) VALUES('세영오토 (데모)','배터리 셀 및 모듈')").lastrowid
            db.execute("INSERT INTO users(email,name,password,role,company_id) VALUES('supplier@example.test','데모 협력사',?,'supplier',?)",(hash_password(password),id))
    print('생성 완료. 관리자:',args.email)
    if args.command=='seed-demo':print('데모 협력사: supplier@example.test (입력한 동일 비밀번호). 실제 데이터에 사용하지 마세요.')

if __name__=='__main__':main()
