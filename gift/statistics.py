"""Read-only spending/quantity aggregates, scoped to the authenticated account."""
import re
from .database import connection
from .services import GiftError,owned,public,today

AGGREGATES='''COUNT(*) records,COALESCE(SUM(quantity),0) units,
 COALESCE(SUM(quantity IS NULL),0) unknown_quantity,
 COALESCE(SUM(total_price),0) amount,
 COALESCE(SUM(total_price IS NULL),0) unknown_amount,
 COALESCE(SUM(purchase_month IS NULL OR purchase_month=''),0) unknown_month'''

def stats(user,params):
    recipient=params.get('recipient_id');year=params.get('year') or ''
    if year and (not re.fullmatch(r'[0-9]{4}',year) or not 1<=int(year)<=9999):raise GiftError('年份不正确')
    level=str(params.get('level') or '1')
    if level not in ('1','2','3'):raise GiftError('分类层级不正确')
    where='user_id=?';args=[user]
    with connection() as conn:
        profile=None
        if recipient:
            profile=public(owned(conn,'gift_recipients',recipient,user));where+=' AND recipient_id=?';args.append(recipient)
        def summary(condition=where,values=args):
            row=dict(conn.execute('SELECT '+AGGREGATES+' FROM gift_items WHERE '+condition,values).fetchone())
            row['amount']/=100
            return row
        lifetime=summary();current=today()[:7]
        current_summary=summary(where+' AND purchase_month=?',args+[current])
        all_months=[dict(row) for row in conn.execute('SELECT purchase_month month,'+AGGREGATES+' FROM gift_items WHERE '+where+" AND purchase_month IS NOT NULL AND purchase_month<>'' GROUP BY purchase_month ORDER BY purchase_month DESC",args)]
        for row in all_months:row['amount']/=100
        filtered_where=where;filtered_args=list(args)
        if year:filtered_where+=' AND purchase_month BETWEEN ? AND ?';filtered_args.extend([year+'-01',year+'-12'])
        selected=summary(filtered_where,filtered_args)
        columns=[f'COALESCE(NULLIF(category_level{i},\'\'),\'未分类\')' for i in range(1,int(level)+1)]
        category_rows=conn.execute('SELECT '+','.join(column+' path'+str(i+1) for i,column in enumerate(columns))+','+AGGREGATES+' FROM gift_items WHERE '+filtered_where+' GROUP BY '+','.join(columns)+' ORDER BY SUM(total_price) DESC,SUM(quantity) DESC,COUNT(*) DESC',filtered_args).fetchall()
        category_stats=[]
        for row in category_rows:
            item=dict(row);item['path']=[item.pop('path'+str(i+1)) for i in range(len(columns))];item['amount']/=100;category_stats.append(item)
        budget_where='user_id=?';budget_args=[user]
        if recipient:budget_where+=' AND id=?';budget_args.append(recipient)
        budget=dict(conn.execute('SELECT COUNT(*) recipients,COUNT(monthly_budget) configured,COALESCE(SUM(monthly_budget),0) amount FROM gift_recipients WHERE '+budget_where,budget_args).fetchone())
        budget['amount']=budget['amount']/100 if budget['configured'] else None
        return {'recipient':profile,'month':current,'year':year,'level':int(level),'lifetime':lifetime,'current':current_summary,'selected':selected,
                'budget':budget,'years':sorted({current[:4],*(m['month'][:4] for m in all_months)},reverse=True),
                'months':[m for m in all_months if not year or m['month'].startswith(year+'-')],'categories':category_stats,
                'active_months':len(all_months),'peak_month':max(all_months,key=lambda m:m['amount']) if all_months else None}
