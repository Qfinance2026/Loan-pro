"""Deterministic Mongolian loan math. Dates are calendar dates, Actual/365."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from calendar import monthrange
D=lambda x: Decimal(str(x))
def q(x): return D(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def month_after(d,n):
    y=d.year+(d.month-1+n)//12; m=(d.month-1+n)%12+1
    return date(y,m,min(d.day,monthrange(y,m)[1]))
def interest(principal,rate,start,end):
    days=(end-start).days
    if days<0: raise ValueError('Огнооны дараалал буруу')
    return q(D(principal)*D(rate)*D(days)/D(36500))
def make_schedule(amount,rate,start,months,method,first_due=None):
    amount=q(amount);rate=D(rate); months=int(months)
    if amount<=0 or rate<0 or months<1 or months>360 or method not in ('annuity','equal','bullet'):
        raise ValueError('Зээлийн нөхцөл буруу')
    # Maintain original calendar anchor including 31st / month-end behavior.
    dates=[start]+[month_after(start,i) for i in range(1,months+1)]
    factors=[D(1)+rate*D((dates[i]-dates[i-1]).days)/D(36500) for i in range(1,months+1)]
    if method=='annuity':
        discount=D(1);acc=D(0)
        for f in factors: discount/=f;acc+=discount
        installment=q(amount/acc)
    balance=amount;rows=[]
    for i in range(1,months+1):
        intr=interest(balance,rate,dates[i-1],dates[i])
        if i==months: principal=balance
        elif method=='annuity': principal=min(balance,max(D(0),installment-intr))
        elif method=='equal':principal=q(amount/months)
        else:principal=D(0)
        principal=q(principal);balance=q(balance-principal)
        rows.append(dict(no=i,due=dates[i],principal=principal,interest=intr,total=q(principal+intr),balance=balance))
    return rows

def state(loan,dues,payments,on):
    """Accrue daily on outstanding principal; overdue penalty on due unpaid principal.
    Payments carry immutable splits computed at posting date. Out-of-order payments forbidden.
    """
    start=loan.start_date; principal=q(loan.amount); accr=D(0); penal=D(0)
    if on<start: return dict(principal=principal,interest=q(0),penalty=q(0),overdue=q(0),days=0,total=principal)
    eligible=[p for p in payments if p.paid_at<=on and not p.voided]
    eligible.sort(key=lambda p:(p.paid_at,p.id or 0))
    events=sorted({on,*[r.due for r in dues if start<=r.due<=on],*[p.paid_at for p in eligible]})
    cur=start; due_pr=D(0); principal_paid=D(0); oldest=None
    for day in events:
        if day>cur:
            accr+=interest(principal,loan.rate,cur,day)
            penal+=interest(min(principal,max(D(0),due_pr-principal_paid)),loan.penalty_rate,cur,day)
            cur=day
        for p in [p for p in eligible if p.paid_at==day]:
            penal=max(D(0),penal-D(p.penalty_paid))
            accr=max(D(0),accr-D(p.interest_paid))
            principal=max(D(0),principal-D(p.principal_paid)); principal_paid+=D(p.principal_paid)
        for r in [r for r in dues if r.due==day]: due_pr+=D(r.principal)
    overdue=q(min(principal,max(D(0),due_pr-principal_paid)))
    if overdue>0:
        running=D(0)
        for r in sorted(dues,key=lambda x:x.due):
            if r.due<on:
                running+=D(r.principal)
                if running>principal_paid:
                    oldest=r.due;break
    return dict(principal=q(principal),interest=q(accr),penalty=q(penal),overdue=overdue,days=(on-oldest).days if oldest else 0,total=q(principal+accr+penal))
