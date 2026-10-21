import calendar, datetime as dt, hashlib, hmac, os, sqlite3, json, shutil, zipfile, tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

Q=Decimal('0.01')
def dec(v): return Decimal(str(v))
def money(v): return dec(v).quantize(Q, rounding=ROUND_HALF_UP)
def iso(v): return dt.date.fromisoformat(str(v))
def add_months(date, n, anchor=None):
    m=date.month-1+n; y=date.year+m//12; month=m%12+1
    d=min(anchor or date.day,calendar.monthrange(y,month)[1]); return dt.date(y,month,d)
def interest(principal, rate, start, end):
    days=(iso(end)-iso(start)).days
    if days<0: raise ValueError('Огнооны дараалал буруу байна')
    return money(dec(principal)*dec(rate)/100*dec(days)/365)
def schedule(amount, rate, start_date, months, method='annuity'):
    amount=money(amount); rate=dec(rate); months=int(months)
    if amount<=0 or rate<0 or months<1 or months>600: raise ValueError('Зээлийн нөхцөл буруу')
    start=iso(start_date); dates=[start]+[add_months(start,i,start.day) for i in range(1,months+1)]
    factors=[dec(1)+rate*dec((dates[i]-dates[i-1]).days)/36500 for i in range(1,months+1)]
    if method=='annuity':
        discount=Decimal(1); total=Decimal(0)
        for f in factors:
            discount/=f; total+=discount
        installment=money(amount/total)
    elif method not in ('equal','bullet'): raise ValueError('Графикийн төрөл буруу')
    rows=[]; balance=amount
    for i in range(1,months+1):
        intr=interest(balance,rate,dates[i-1],dates[i])
        if i==months: principal=balance
        elif method=='annuity': principal=max(Decimal(0),min(balance, installment-intr))
        elif method=='equal': principal=min(balance,money(amount/months))
        else: principal=Decimal(0)
        principal=money(principal); balance=money(balance-principal)
        rows.append({'no':i,'due_date':str(dates[i]),'principal':principal,'interest':intr,'total':money(principal+intr),'balance':balance})
    return rows

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS borrowers(id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK(type IN ('Иргэн','Байгууллага')), name TEXT NOT NULL, registration TEXT, phone TEXT, address TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY, borrower_id INTEGER NOT NULL REFERENCES borrowers(id), contract TEXT NOT NULL UNIQUE, amount TEXT NOT NULL, annual_rate TEXT NOT NULL, penalty_rate TEXT NOT NULL DEFAULT '0', months INTEGER NOT NULL, start_date TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Идэвхтэй', notes TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_rows(id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(id), version INTEGER NOT NULL DEFAULT 1, installment_no INTEGER NOT NULL, due_date TEXT NOT NULL, principal TEXT NOT NULL, interest TEXT NOT NULL, total TEXT NOT NULL, balance TEXT NOT NULL, UNIQUE(loan_id,version,installment_no));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(id), payment_date TEXT NOT NULL, amount TEXT NOT NULL, penalty_applied TEXT NOT NULL, interest_applied TEXT NOT NULL, principal_applied TEXT NOT NULL, unallocated TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collaterals(id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(id), category TEXT NOT NULL, description TEXT, valuation TEXT NOT NULL DEFAULT '0');
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(id), display_name TEXT NOT NULL, stored_name TEXT NOT NULL, added_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, detail TEXT, ts TEXT NOT NULL);
'''

def now(): return dt.datetime.now().isoformat(timespec='seconds')
class Store:
    def __init__(self,folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.attach=self.folder/'attachments';self.attach.mkdir(exist_ok=True)
        self.db=self.folder/'loans.sqlite3'
        self.con=sqlite3.connect(self.db);self.con.row_factory=sqlite3.Row;self.con.execute('PRAGMA foreign_keys=ON');self.con.execute('PRAGMA busy_timeout=3000');self.con.executescript(SCHEMA);self.con.commit()
    def close(self):self.con.close()
    def audit(self,action,entity,id,detail=''):
        self.con.execute('INSERT INTO audit(action,entity,entity_id,detail,ts) VALUES(?,?,?,?,?)',(action,entity,id,detail,now()))
    def has_user(self): return self.con.execute('SELECT COUNT(*) FROM users').fetchone()[0]>0
    def make_user(self,name,password):
        if self.has_user(): raise ValueError('Хэрэглэгч үүссэн байна')
        if len(password)<8: raise ValueError('Нууц үг 8-аас дээш тэмдэгттэй байх ёстой')
        salt=os.urandom(16); derived=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1)
        with self.con: self.con.execute('INSERT INTO users(username,salt,password_hash) VALUES(?,?,?)',(name,salt,derived))
    def login(self,name,password):
        u=self.con.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
        return bool(u and hmac.compare_digest(u['password_hash'],hashlib.scrypt(password.encode(),salt=u['salt'],n=2**14,r=8,p=1)))
    def borrower(self,kind,name,registration='',phone='',address=''):
        if not name.strip(): raise ValueError('Нэр хоосон')
        with self.con:
            c=self.con.execute('INSERT INTO borrowers(type,name,registration,phone,address,created_at) VALUES(?,?,?,?,?,?)',(kind,name.strip(),registration,phone,address,now()));self.audit('create','borrower',c.lastrowid,name)
        return c.lastrowid
    def new_loan(self,borrower_id,contract,amount,rate,penalty_rate,months,start,method,notes=''):
        rows=schedule(amount,rate,start,months,method)
        if dec(penalty_rate)<0: raise ValueError('Нэмэгдүүлсэн хүү сөрөг байж болохгүй')
        with self.con:
            c=self.con.execute('INSERT INTO loans(borrower_id,contract,amount,annual_rate,penalty_rate,months,start_date,method,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(borrower_id,contract,str(money(amount)),str(dec(rate)),str(dec(penalty_rate)),months,str(iso(start)),method,notes,now()))
            lid=c.lastrowid
            self._rows(lid,1,rows)
            self.audit('create','loan',lid,contract)
        return lid
    def _rows(self,lid,version,rows):
        self.con.executemany('INSERT INTO schedule_rows(loan_id,version,installment_no,due_date,principal,interest,total,balance) VALUES(?,?,?,?,?,?,?,?)',[(lid,version,r['no'],r['due_date'],str(r['principal']),str(r['interest']),str(r['total']),str(r['balance'])) for r in rows])
    def loans(self):
        return self.con.execute('SELECT l.*,b.name AS borrower FROM loans l JOIN borrowers b ON b.id=l.borrower_id ORDER BY l.id DESC').fetchall()
    def loan(self,lid):return self.con.execute('SELECT * FROM loans WHERE id=?',(lid,)).fetchone()
    def schedules(self,lid):
        return self.con.execute('SELECT * FROM schedule_rows WHERE loan_id=? AND version=(SELECT MAX(version) FROM schedule_rows WHERE loan_id=?) ORDER BY installment_no',(lid,lid)).fetchall()
    def payments(self,lid):return self.con.execute('SELECT * FROM payments WHERE loan_id=? ORDER BY payment_date,id',(lid,)).fetchall()
    def state(self,lid,asof=None):
        loan=self.loan(lid)
        if loan is None:raise ValueError('Зээл олдсонгүй')
        end=iso(asof or dt.date.today()); start=iso(loan['start_date'])
        if end<start: return {'principal':money(loan['amount']),'interest':Decimal('0'),'penalty':Decimal('0'),'overdue_days':0,'overdue_principal':Decimal('0'),'total':money(loan['amount'])}
        principal=money(loan['amount']);accrued=Decimal(0);penalty=Decimal(0); cur=start
        dues=list(self.schedules(lid))
        pay=list(self.con.execute('SELECT * FROM payments WHERE loan_id=? AND payment_date<=? ORDER BY payment_date,id',(lid,str(end))))
        events=sorted(set([end]+[iso(x['due_date']) for x in dues if start<=iso(x['due_date'])<=end]+[iso(p['payment_date']) for p in pay if start<=iso(p['payment_date'])<=end]))
        due_principal=Decimal(0); allocated_principal=Decimal(0)
        for day in events:
            if day>cur:
                accrued+=interest(principal,loan['annual_rate'],cur,day)
                # Penalty on outstanding scheduled principal, never more than actual balance.
                overdue_base=max(Decimal(0),min(principal,due_principal-allocated_principal))
                penalty+=interest(overdue_base,loan['penalty_rate'],cur,day)
                cur=day
            for p in (p for p in pay if iso(p['payment_date'])==day):
                penalty=max(Decimal(0),penalty-dec(p['penalty_applied']))
                accrued=max(Decimal(0),accrued-dec(p['interest_applied']))
                principal=max(Decimal(0),principal-dec(p['principal_applied']))
                allocated_principal+=dec(p['principal_applied'])
            for row in (x for x in dues if iso(x['due_date'])==day):due_principal+=dec(row['principal'])
        overdue_principal=max(Decimal(0),min(principal,due_principal-allocated_principal))
        outstanding=[iso(r['due_date']) for r in dues if iso(r['due_date'])<end]
        overdue_days=(end-min(outstanding)).days if overdue_principal>0 and outstanding else 0
        return {'principal':money(principal),'interest':money(accrued),'penalty':money(penalty),'overdue_days':overdue_days,'overdue_principal':money(overdue_principal),'total':money(principal+accrued+penalty)}
    def add_payment(self,lid,date,amount,note='',prepay='keep'):
        loan=self.loan(lid); date=iso(date); amount=money(amount)
        if not loan:raise ValueError('Зээл олдсонгүй')
        if amount<=0 or date<iso(loan['start_date']) or date>dt.date.today():raise ValueError('Төлөлтийн дүн эсвэл огноо буруу')
        last=self.con.execute('SELECT MAX(payment_date) FROM payments WHERE loan_id=?',(lid,)).fetchone()[0]
        if last and str(date)<last:raise ValueError('Өмнөх төлөлтөөс эрт огноогоор оруулахгүй')
        st=self.state(lid,date); remaining=amount
        penalty=min(remaining,st['penalty']);remaining-=penalty
        intr=min(remaining,st['interest']);remaining-=intr
        principal=min(remaining,st['principal']);remaining-=principal
        if remaining>0:raise ValueError('Төлөх дүн нийт өрөөс их байна')
        with self.con:
            c=self.con.execute('INSERT INTO payments(loan_id,payment_date,amount,penalty_applied,interest_applied,principal_applied,unallocated,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(lid,str(date),str(amount),str(penalty),str(intr),str(principal),'0',note,now()))
            self.audit('payment','loan',lid,f'{date}: {amount}; fee {penalty}, interest {intr}, principal {principal}')
            if prepay!='keep' and principal>0 and st['principal']>principal:
                self.reschedule(lid,date,prepay)
        return c.lastrowid
    def reschedule(self,lid,asof,mode):
        # A conservative reset: preserve earlier rows, replace only future installments with a schedule on remaining principal.
        # Original maturity is preserved for reduce-payment; reduce-term uses previous total payment as target.
        loan=self.loan(lid); st=self.state(lid,asof); old=self.schedules(lid)
        remaining_count=sum(1 for x in old if iso(x['due_date'])>iso(asof))
        if not remaining_count or st['principal']<=0:return
        months=remaining_count
        if mode=='reduce-term' and loan['method']=='annuity':
            current=max((dec(r['total']) for r in old if iso(r['due_date'])>iso(asof)),default=Decimal(0))
            for m in range(1,months+1):
                trial=schedule(st['principal'],loan['annual_rate'],asof,m,loan['method'])
                if trial[0]['total']<=current:months=m;break
        new=schedule(st['principal'],loan['annual_rate'],asof,months,loan['method'])
        # Retain prior scheduled dues for payment/overdue reconciliation.
        previous=[{'no':i+1,'due_date':r['due_date'],'principal':dec(r['principal']),'interest':dec(r['interest']),'total':dec(r['total']),'balance':dec(r['balance'])} for i,r in enumerate(x for x in old if iso(x['due_date'])<=iso(asof))]
        new=[dict(r,no=len(previous)+i+1) for i,r in enumerate(new)]
        new=previous+new
        ver=self.con.execute('SELECT COALESCE(MAX(version),0)+1 FROM schedule_rows WHERE loan_id=?',(lid,)).fetchone()[0]
        self._rows(lid,ver,new)
        self.audit('reschedule','loan',lid,f'{mode} on {asof}; version {ver}')
    def add_collateral(self,lid,category,description,valuation):
        with self.con:
            c=self.con.execute('INSERT INTO collaterals(loan_id,category,description,valuation) VALUES(?,?,?,?)',(lid,category,description,str(money(valuation))));self.audit('collateral','loan',lid,category)
    def add_document(self,lid,path):
        path=Path(path)
        if not path.is_file():raise ValueError('Файл олдсонгүй')
        import uuid
        name=uuid.uuid4().hex+path.suffix.lower();shutil.copy2(path,self.attach/name)
        with self.con:
            self.con.execute('INSERT INTO documents(loan_id,display_name,stored_name,added_at) VALUES(?,?,?,?)',(lid,path.name,name,now()));self.audit('document','loan',lid,path.name)
    def backup(self,target):
        target=Path(target)
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/'loans.sqlite3'
            with sqlite3.connect(dest) as co:self.con.backup(co)
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(dest,'loans.sqlite3')
                for f in self.attach.iterdir():
                    if f.is_file():z.write(f,'attachments/'+f.name)
        self.audit('backup','system',None,target.name);self.con.commit()
    def restore(self,archive):
        # Restores only after UI closes connection; call standalone restore_archive.
        raise NotImplementedError

def restore_archive(archive,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist())
        if 'loans.sqlite3' not in names or any(n.startswith('/') or '..' in Path(n).parts for n in names):raise ValueError('Нөөцийн файл буруу')
        with tempfile.TemporaryDirectory() as t:
            z.extractall(t)
            src=sqlite3.connect(str(Path(t)/'loans.sqlite3'))
            ok=src.execute('PRAGMA integrity_check').fetchone()[0];src.close()
            if ok!='ok':raise ValueError('Өгөгдлийн сан гэмтсэн')
            shutil.copy2(Path(t)/'loans.sqlite3',folder/'loans.sqlite3')
            dest=folder/'attachments';dest.mkdir(exist_ok=True)
            for f in (Path(t)/'attachments').glob('*') if (Path(t)/'attachments').exists() else []:
                if f.is_file():shutil.copy2(f,dest/f.name)
