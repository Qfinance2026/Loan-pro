from datetime import date
from decimal import Decimal
from engine import make_schedule,interest,state
from types import SimpleNamespace

def test_interest_actual365():
 assert interest(100_000_000,24,date(2026,1,1),date(2026,1,2))==Decimal('65753.42')
def test_schedule_all():
 for method in ('annuity','equal','bullet'):
  rows=make_schedule(100_000_000,24,date(2026,1,15),12,method)
  assert len(rows)==12 and rows[-1]['balance']==0
  assert sum(x['principal'] for x in rows)==100_000_000
  assert all(x['total']==x['interest']+x['principal'] for x in rows)
  if method=='bullet':assert all(x['principal']==0 for x in rows[:-1])
def test_state_accrued_and_payment():
 start=date(2026,1,1)
 loan=SimpleNamespace(amount=Decimal('1000000'),rate=Decimal('24'),penalty_rate=Decimal('4.8'),start_date=start)
 dues=[SimpleNamespace(due=date(2026,2,1),principal=Decimal('100000'),interest=Decimal('0'))]
 s=state(loan,dues,[],date(2026,2,5))
 assert s['principal']==1_000_000 and s['overdue']==100_000 and s['days']==4 and s['penalty']>0
 p=SimpleNamespace(id=1,paid_at=date(2026,2,5),penalty_paid=s['penalty'],interest_paid=s['interest'],principal_paid=Decimal('50000'),voided=False)
 s2=state(loan,dues,[p],date(2026,2,5))
 assert s2['principal']==950_000 and s2['interest']==0 and s2['penalty']==0
