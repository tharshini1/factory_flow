#!/usr/bin/env python3
"""Order-to-Audit system. Pure Python stdlib + SQLite: zero dependencies, one command to run.
Money = integer paise. Quantities = integer base units (g, ml, pcs). Stock = SUM(ledger)."""
from contextlib import closing
import os,sqlite3,json,hashlib,secrets,csv,io,re,datetime,threading,math
from decimal import Decimal,ROUND_HALF_UP
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
ROOT=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get("DB_PATH",os.path.join(ROOT,"factory.db"))
HOME_STATE="Tamil Nadu"; TOL_BP=300  # variance tolerance 3.00%
LOCK=threading.Lock()
class E(Exception):
    def __init__(s,msg,code=400): s.msg=msg; s.code=code
def now(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def today(): return datetime.date.today().isoformat()
def conn():
    c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; c.execute("pragma foreign_keys=on"); return c
def rows(c,sql,*a): return [dict(r) for r in c.execute(sql,a)]
def one(c,sql,*a):
    r=c.execute(sql,a).fetchone(); return dict(r) if r else None
def pw(p): return hashlib.sha256(("murukku:"+p).encode()).hexdigest()
def paise(x): return int((Decimal(str(x or 0))*100).to_integral_value(ROUND_HALF_UP))
def base(x,f): return int((Decimal(str(x or 0))*f).to_integral_value(ROUND_HALF_UP))
def disp(q,f): return format((Decimal(q)/f).normalize(),"f") if q else "0"
def R(p): return f"{Decimal(p)/100:.2f}"
def fy(d=None):
    d=d or datetime.date.today(); y=d.year if d.month>=4 else d.year-1; return f"{y}-{(y+1)%100:02d}"

SCHEMA="""
create table if not exists users(id integer primary key,username text unique,pw text,role text,name text);
create table if not exists sessions(token text primary key,user_id int);
create table if not exists items(id integer primary key,name text,kind text,unit text,factor int,price int default 0,hsn text default '',gst int default 5,yield int default 0,reorder int default 0);
create table if not exists bom(product_id int,item_id int,qty int,role text default '');
create table if not exists ledger(id integer primary key,ts text,item_id int,qty int,value int,doc_type text,doc_id int,note text default '',batch text default '');
create table if not exists customers(id integer primary key,name text,kind text,gstin text,state text,phone text,address text);
create table if not exists orders(id integer primary key,no text,client_id text unique,salesman_id int,customer_id int,status text,ts text,note text default '');
create table if not exists order_lines(id integer primary key,order_id int,item_id int,qty int,price int);
create table if not exists invoices(id integer primary key,no text unique,order_id int,customer_id int,date text,taxable int,cgst int,sgst int,igst int,total int,status text default 'active',dispatched int default 0,cn_no text);
create table if not exists invoice_lines(id integer primary key,invoice_id int,item_id int,qty int,price int,hsn text,rate int,taxable int,cgst int,sgst int,igst int);
create table if not exists payments(id integer primary key,invoice_id int,customer_id int,amount int,mode text,ts text,user text);
create table if not exists purchases(id integer primary key,supplier text,item_id int,qty int,rate int,total int,date text);
create table if not exists runs(id integer primary key,batch_no text,product_id int,batches int,good int,damaged int,expected int,labour int default 0,power int default 0,mat_cost int,ts text,user text);
create table if not exists run_lines(run_id int,item_id int,planned int,actual int,value int);
create table if not exists audit(id integer primary key,ts text,user text,action text,ref text,detail text);
"""
def audit(c,u,action,ref,detail=""): c.execute("insert into audit(ts,user,action,ref,detail) values(?,?,?,?,?)",(now(),u["username"] if u else "system",action,ref,detail))
def led(c,item,qty,value,doc,did,note="",batch=""): c.execute("insert into ledger(ts,item_id,qty,value,doc_type,doc_id,note,batch) values(?,?,?,?,?,?,?,?)",(now(),item,qty,value,doc,did,note,batch))
def bal(c,item):
    r=c.execute("select coalesce(sum(qty),0),coalesce(sum(value),0) from ledger where item_id=?",(item,)).fetchone(); return r[0],r[1]
def out_value(c,item,q):  # perpetual weighted-average cost of the units leaving
    s,v=bal(c,item); return (v*q+s//2)//s if s>0 else 0

def seed():
    c=conn(); c.executescript(SCHEMA)
    if c.execute("select count(*) from users").fetchone()[0]: c.close(); return
    for u,r,n in [("sales_a","salesman","Salesman A"),("sales_b","salesman","Salesman B"),("admin","admin","Factory Admin"),("production","production","Production Supervisor"),("auditor","accountant","Auditor"),("owner","owner","Owner")]:
        c.execute("insert into users(username,pw,role,name) values(?,?,?,?)",(u,pw("demo123"),r,n))
    I=[(1,"Flour","raw","kg",1000,0,"1101",5,0,50),(2,"Cooking oil","raw","L",1000,0,"1513",5,0,15),(3,"Salt and spice mix","raw","kg",1000,0,"0910",5,0,2),
       (4,"200 g pouch","pack","pcs",1,0,"3923",18,0,100),(5,"Carton (20 packets)","pack","pcs",1,0,"4819",12,0,10),(6,"Murukku 200 g","fg","packets",1,5000,"2106",5,200,40),
       (7,"Besan (gram flour)","raw","kg",1000,0,"1106",5,0,15),(8,"Sugar","raw","kg",1000,0,"1701",5,0,15),(9,"Ghee","raw","kg",1000,0,"0405",12,0,5),(10,"Potatoes","raw","kg",1000,0,"0701",0,0,20),
       (11,"250 g sweet box","pack","pcs",1,0,"4819",12,0,50),(12,"Mixture 200 g","fg","packets",1,6000,"2106",5,200,40),(13,"Potato Chips 150 g","fg","packets",1,4000,"2005",12,100,40),(14,"Mysore Pak 250 g","fg","packets",1,12000,"1704",5,80,20)]
    c.executemany("insert into items(id,name,kind,unit,factor,price,hsn,gst,yield,reorder) values(?,?,?,?,?,?,?,?,?,?)",I)
    c.executemany("insert into bom values(?,?,?,?)",[(6,1,40000,""),(6,2,10000,""),(6,3,1200,""),(6,4,200,"pouch"),(6,5,10,"carton"),
        (12,7,20000,""),(12,1,15000,""),(12,2,8000,""),(12,3,1500,""),(12,4,200,"pouch"),(12,5,10,"carton"),
        (13,10,40000,""),(13,2,8000,""),(13,3,500,""),(13,4,100,"pouch"),(13,5,5,"carton"),
        (14,7,5000,""),(14,8,10000,""),(14,9,8000,""),(14,11,80,"pouch"),(14,5,4,"carton")])
    for it,q,rate in [(1,100000,4200),(2,30000,14000),(3,5000,20000),(4,500,250),(5,30,1500),(6,50,3000),(7,40000,9000),(8,40000,4500),(9,20000,55000),(10,100000,2200),(11,300,800),(12,120,3500),(13,80,2500),(14,40,9000)]:
        f=one(c,"select factor from items where id=?",it)["factor"]; led(c,it,q,(q*rate+f//2)//f,"opening",0,"Opening balance")
    c.executemany("insert into customers(name,kind,gstin,state,phone,address) values(?,?,?,?,?,?)",[
        ("Retailer A","Retailer","33AABCR1234A1Z5","Tamil Nadu","9840000001","Trichy"),("Distributor B","Distributor","29AABCD5678B1Z2","Karnataka","9840000002","Bengaluru")])
    c.commit(); c.close()

# ---------- handlers ----------
def items_view(c,kind=None):
    out=[]
    for it in rows(c,"select * from items order by id"):
        s,v=bal(c,it["id"]); f=it["factor"]
        it.update(stock=disp(s,f),stock_base=s,value=v,avg=round(v*f/s) if s else 0,low=bool(it["reorder"] and s<it["reorder"]*f),reorder_disp=it["reorder"])
        if it["kind"]=="fg": it["bom"]=rows(c,"select b.item_id,i.name,i.unit,i.factor,b.qty,b.role from bom b join items i on i.id=b.item_id where product_id=?",it["id"])
        out.append(it)
    return out
def order_view(c,o):
    o["customer"]=one(c,"select * from customers where id=?",o["customer_id"]); o["salesman"]=one(c,"select name from users where id=?",o["salesman_id"])["name"]
    L=rows(c,"select l.*,i.name,i.unit,i.factor from order_lines l join items i on i.id=l.item_id where order_id=?",o["id"]); tot=0
    for l in L:
        s,_=bal(c,l["item_id"]); l["amount"]=l["qty"]*l["price"]//l["factor"]; tot+=l["amount"]
        l["stock"]=disp(s,l["factor"]); l["short"]=max(0,l["qty"]-s); l["qty_disp"]=disp(l["qty"],l["factor"]); l["short_disp"]=disp(l["short"],l["factor"]); l["avail"]=max(0,s)
        fg=one(c,"select yield from items where id=?",l["item_id"])["yield"]; l["batches_needed"]=math.ceil(l["short"]/fg) if fg and l["short"] else 0
    o["lines"]=L; o["total"]=tot; o["short"]=any(l["short"] for l in L)
    o["invoice"]=one(c,"select * from invoices where order_id=? and status='active'",o["id"]); return o
def list_orders(c,u,b,p,m):
    sql="select * from orders"+(" where salesman_id=?" if u["role"]=="salesman" else "")+" order by id desc limit 200"
    return [order_view(c,o) for o in rows(c,sql,*([u["id"]] if u["role"]=="salesman" else []))]
def new_order(c,u,b,p,m):
    cid=b.get("client_id") or secrets.token_hex(6); ex=one(c,"select * from orders where client_id=?",cid)
    if ex: return order_view(c,ex)  # idempotent: offline sync can retry safely
    lines=[l for l in b.get("lines",[]) if Decimal(str(l.get("qty") or 0))>0]
    if not lines or not b.get("customer_id"): raise E("Pick a customer and add at least one product.")
    n=c.execute("select count(*) from orders").fetchone()[0]+1
    cur=c.execute("insert into orders(no,client_id,salesman_id,customer_id,status,ts) values(?,?,?,?,?,?)",(f"ORD-{n:04d}",cid,u["id"],b["customer_id"],"submitted",b.get("ts") or now()))
    for l in lines:
        it=one(c,"select * from items where id=? and kind='fg'",l["item_id"]); c.execute("insert into order_lines(order_id,item_id,qty,price) values(?,?,?,?)",(cur.lastrowid,it["id"],base(l["qty"],it["factor"]),it["price"]))
    audit(c,u,"order.create",f"ORD-{n:04d}"); return order_view(c,one(c,"select * from orders where id=?",cur.lastrowid))
def get_order(c,oid):
    o=one(c,"select * from orders where id=?",oid)
    if not o: raise E("Order not found",404)
    return o
def edit_order(c,u,b,p,m):
    o=get_order(c,m[0])
    if o["status"] not in("submitted","approved"): raise E("Only open orders can be edited.")
    for l in b["lines"]:
        row=one(c,"select l.id,i.factor from order_lines l join items i on i.id=l.item_id where l.id=? and order_id=?",l["id"],o["id"])
        if Decimal(str(l["qty"]))<=0: c.execute("delete from order_lines where id=?",(row["id"],))
        else: c.execute("update order_lines set qty=?,price=? where id=?",(base(l["qty"],row["factor"]),paise(l["price"]),row["id"]))
    if not c.execute("select 1 from order_lines where order_id=?",(o["id"],)).fetchone(): raise E("An order needs at least one line.")
    c.execute("update orders set status='submitted' where id=?",(o["id"],)); audit(c,u,"order.edit",o["no"]); return order_view(c,get_order(c,o["id"]))
def approve(c,u,b,p,m):
    o=order_view(c,get_order(c,m[0]))
    if o["status"]!="submitted": raise E("Order is already "+o["status"])
    if o["short"] and not b.get("force"): raise E("Stock does not cover this order. Reduce quantities, plan production, or approve as backorder.")
    c.execute("update orders set status='approved' where id=?",(o["id"],)); audit(c,u,"order.approve",o["no"],"backorder" if o["short"] else ""); return order_view(c,get_order(c,o["id"]))
def reject(c,u,b,p,m):
    o=get_order(c,m[0])
    if o["status"] not in("submitted","approved"): raise E("Cannot reject now.")
    c.execute("update orders set status='rejected' where id=?",(o["id"],)); audit(c,u,"order.reject",o["no"]); return order_view(c,get_order(c,o["id"]))
def tax_split(taxable,rate,inter):
    t=(taxable*rate+50)//100
    return (0,0,t) if inter else (t//2,t-t//2,0)
def invoice(c,u,b,p,m):
    o=order_view(c,get_order(c,m[0]))
    if o["status"]!="approved": raise E("Approve the order before invoicing.")
    cust=o["customer"]; inter=cust["state"]!=HOME_STATE
    n=c.execute("select count(*) from invoices where no like ?",(f"INV/{fy()}/%",)).fetchone()[0]+1; no=f"INV/{fy()}/{n:04d}"
    cur=c.execute("insert into invoices(no,order_id,customer_id,date,taxable,cgst,sgst,igst,total) values(?,?,?,?,0,0,0,0,0)",(no,o["id"],cust["id"],today())); iid=cur.lastrowid; T=[0,0,0,0]
    for l in o["lines"]:
        it=one(c,"select hsn,gst from items where id=?",l["item_id"]); cg,sg,ig=tax_split(l["amount"],it["gst"],inter)
        c.execute("insert into invoice_lines(invoice_id,item_id,qty,price,hsn,rate,taxable,cgst,sgst,igst) values(?,?,?,?,?,?,?,?,?,?)",(iid,l["item_id"],l["qty"],l["price"],it["hsn"],it["gst"],l["amount"],cg,sg,ig))
        for k,v in enumerate((l["amount"],cg,sg,ig)): T[k]+=v
    c.execute("update invoices set taxable=?,cgst=?,sgst=?,igst=?,total=? where id=?",(*T,sum(T),iid)); c.execute("update orders set status='invoiced' where id=?",(o["id"],))
    audit(c,u,"invoice.create",no,f"total {R(sum(T))}"); return {"id":iid,"no":no}
def dispatch(c,u,b,p,m):
    o=order_view(c,get_order(c,m[0])); inv=o["invoice"]
    if o["status"]!="invoiced" or not inv: raise E("Raise the invoice first.")
    if o["short"]: raise E("Cannot dispatch: short by "+", ".join(f"{l['short_disp']} {l['unit']} of {l['name']}" for l in o["lines"] if l["short"])+". Produce more or edit the quantity.")
    for l in o["lines"]: led(c,l["item_id"],-l["qty"],-out_value(c,l["item_id"],l["qty"]),"invoice",inv["id"],f"Dispatch {inv['no']}")
    c.execute("update invoices set dispatched=1 where id=?",(inv["id"],)); c.execute("update orders set status='dispatched' where id=?",(o["id"],)); audit(c,u,"dispatch",inv["no"]); return order_view(c,get_order(c,o["id"]))
def cancel_invoice(c,u,b,p,m):
    inv=one(c,"select * from invoices where id=?",m[0])
    if not inv or inv["status"]!="active": raise E("Invoice not active.")
    cn=f"CN/{fy()}/{c.execute('select count(*) from invoices where cn_no is not null').fetchone()[0]+1:04d}"
    if inv["dispatched"]:
        for r in rows(c,"select * from ledger where doc_type='invoice' and doc_id=?",inv["id"]): led(c,r["item_id"],-r["qty"],-r["value"],"credit_note",inv["id"],f"Credit note {cn} reverses {inv['no']}")
    c.execute("update invoices set status='cancelled',cn_no=? where id=?",(cn,inv["id"])); c.execute("update orders set status='approved' where id=?",(inv["order_id"],)); audit(c,u,"invoice.cancel",inv["no"],cn); return {"cn_no":cn}
def pay(c,u,b,p,m):
    inv=one(c,"select * from invoices where id=? and status='active'",b.get("invoice_id")); amt=paise(b.get("amount"))
    if not inv or amt<=0: raise E("Choose an invoice and enter an amount.")
    c.execute("insert into payments(invoice_id,customer_id,amount,mode,ts,user) values(?,?,?,?,?,?)",(inv["id"],inv["customer_id"],amt,b.get("mode","UPI"),now(),u["username"])); audit(c,u,"payment",inv["no"],R(amt)); return {"ok":1}
def purchase(c,u,b,p,m):
    it=one(c,"select * from items where id=? and kind!='fg'",b.get("item_id")); q=base(b.get("qty"),it["factor"]) if it else 0; rate=paise(b.get("rate"))
    if not it or q<=0 or rate<=0: raise E("Choose a material, quantity and rate.")
    tot=(q*rate+it["factor"]//2)//it["factor"]; cur=c.execute("insert into purchases(supplier,item_id,qty,rate,total,date) values(?,?,?,?,?,?)",(b.get("supplier") or "Local supplier",it["id"],q,rate,tot,today()))
    led(c,it["id"],q,tot,"purchase",cur.lastrowid,b.get("supplier") or "Local supplier"); audit(c,u,"purchase",it["name"],R(tot)); return {"ok":1}
def run_view(c,r):
    pr=one(c,"select * from items where id=?",r["product_id"]); r["product"]=pr["name"]
    L=rows(c,"select l.*,i.name,i.unit,i.factor from run_lines l join items i on i.id=l.item_id where run_id=?",r["id"])
    for l in L:
        l["var_bp"]=(l["actual"]-l["planned"])*10000//l["planned"] if l["planned"] else 0; l["flag"]=abs(l["var_bp"])>TOL_BP; l["planned_disp"]=disp(l["planned"],l["factor"]); l["actual_disp"]=disp(l["actual"],l["factor"])
    r["lines"]=L; r["yield_bp"]=(r["good"]-r["expected"])*10000//r["expected"]; r["yield_flag"]=abs(r["yield_bp"])>TOL_BP
    r["total_cost"]=r["mat_cost"]+r["labour"]+r["power"]; r["cpp"]=float(Decimal(r["total_cost"])/r["good"]) if r["good"] else 0; r["margin"]=pr["price"]-r["cpp"]; r["margin_pct"]=r["margin"]*100/pr["price"] if pr["price"] else 0
    r["flags"]=sum(l["flag"] for l in L)+int(r["yield_flag"]); return r
def new_run(c,u,b,p,m):
    pr=one(c,"select * from items where id=? and kind='fg'",b.get("product_id")); B=int(b.get("batches") or 1)
    if not pr: raise E("Choose a product.")
    good=base(b.get("good"),1); dmg=base(b.get("damaged"),1); bom=rows(c,"select * from bom where product_id=?",pr["id"]); act={}
    if good<0 or dmg<0 or good+dmg==0: raise E("Enter the actual output.")
    for r in bom:
        f=one(c,"select factor,name from items where id=?",r["item_id"])
        act[r["item_id"]]=good+dmg if r["role"]=="pouch" else base((b.get("actual") or {}).get(str(r["item_id"]),0),f["factor"])
        s,_=bal(c,r["item_id"])
        if act[r["item_id"]]>s: raise E(f"Not enough {f['name']} in stock (have {disp(s,f['factor'])}).")
    cur=c.execute("insert into runs(batch_no,product_id,batches,good,damaged,expected,mat_cost,ts,user) values('',?,?,?,?,?,0,?,?)",(pr["id"],B,good,dmg,pr["yield"]*B,now(),u["username"])); rid=cur.lastrowid
    bn=f"MUR{datetime.date.today():%y%m%d}-{rid}"; mat=0
    for r in bom:
        a=act[r["item_id"]]; v=out_value(c,r["item_id"],a); mat+=v
        c.execute("insert into run_lines values(?,?,?,?,?)",(rid,r["item_id"],r["qty"]*B,a,v)); led(c,r["item_id"],-a,-v,"production",rid,f"Issued to run {bn}",bn)
    led(c,pr["id"],good,mat,"production",rid,f"Output of run {bn}",bn); c.execute("update runs set batch_no=?,mat_cost=? where id=?",(bn,mat,rid)); audit(c,u,"run.create",bn); return run_view(c,one(c,"select * from runs where id=?",rid))
def overheads(c,u,b,p,m):
    r=one(c,"select * from runs where id=?",m[0]); lab,pw_=paise(b.get("labour")),paise(b.get("power")); delta=lab+pw_-r["labour"]-r["power"]
    c.execute("update runs set labour=?,power=? where id=?",(lab,pw_,r["id"]))
    if delta: led(c,r["product_id"],0,delta,"production",r["id"],"Overhead absorbed into finished-goods value",r["batch_no"])
    audit(c,u,"run.overheads",r["batch_no"],f"labour {R(lab)} power {R(pw_)}"); return run_view(c,one(c,"select * from runs where id=?",r["id"]))
def list_runs(c,u,b,p,m): return [run_view(c,r) for r in rows(c,"select * from runs order by id desc limit 50")]
def customers(c,u,b,p,m): return rows(c,"select * from customers order by name")
def mysales(c,u,b,p,m):
    return rows(c,"""select c.name,count(distinct o.id) orders,coalesce(sum(l.qty*l.price/i.factor),0) amount from orders o join customers c on c.id=o.customer_id
      join order_lines l on l.order_id=o.id join items i on i.id=l.item_id where o.salesman_id=? and o.status!='rejected' group by c.id order by amount desc""",u["id"])
def ledger_q(c,u,b,p,m):
    it=int(p.get("item",[0])[0] or 0); I=one(c,"select * from items where id=?",it); run=0; out=[]
    for r in rows(c,"select * from ledger where item_id=? order by id",it):
        run+=r["qty"]; r["in"]=disp(r["qty"],I["factor"]) if r["qty"]>0 else ""; r["out"]=disp(-r["qty"],I["factor"]) if r["qty"]<0 else ""; r["balance"]=disp(run,I["factor"]); out.append(r)
    return out[::-1]
def outstanding_rows(c):
    out=[]
    for i in rows(c,"select i.*,c.name cname from invoices i join customers c on c.id=i.customer_id where status='active' order by i.id"):
        paid=c.execute("select coalesce(sum(amount),0) from payments where invoice_id=?",(i["id"],)).fetchone()[0]; i["paid"]=paid; i["due"]=i["total"]-paid
        i["age"]=(datetime.date.today()-datetime.date.fromisoformat(i["date"])).days; out.append(i)
    return out
def invoices_q(c,u,b,p,m): return outstanding_rows(c)
def dashboard(c,u,b,p,m):
    od=outstanding_rows(c); mo=today()[:7]
    runs=[run_view(c,r) for r in rows(c,"select * from runs order by id desc limit 10")]; al=[]
    for r in runs:
        for l in r["lines"]:
            if l["flag"]: al.append(f"{r['batch_no']}: {l['name']} {l['var_bp']/100:+.1f}% vs standard")
        if r["yield_flag"]: al.append(f"{r['batch_no']}: yield {r['yield_bp']/100:+.1f}% ({disp(r['good'],1)} vs {r['expected']} expected)")
    return {"orders_today":c.execute("select count(*) from orders where date(ts)=?",(today(),)).fetchone()[0],"pending":c.execute("select count(*) from orders where status='submitted'").fetchone()[0],
      "sales_month":sum(i["total"] for i in od if i["date"].startswith(mo)),"outstanding":sum(i["due"] for i in od),"stock":[i for i in items_view(c)],"alerts":al,"last_run":runs[0] if runs else None,
      "dues":sorted([{"name":n,"due":sum(i["due"] for i in od if i["cname"]==n)} for n in {i["cname"] for i in od}],key=lambda x:-x["due"])}

def date_f(p,col):
    f,t=p.get("from",[""])[0],p.get("to",[""])[0]; w,a="",[]
    if f: w+=f" and {col}>=?"; a.append(f)
    if t: w+=f" and {col}<=?"; a.append(t+" 99")
    return w,a
def report(c,u,b,p,m):
    n=m[0]; df,dt=date_f(p,"date"); T=lambda cols,rs:{"title":n,"columns":cols,"rows":rs}
    if n=="sales":
        return T(["Invoice","Date","Customer","GSTIN","Place of supply","Taxable","CGST","SGST","IGST","Total","Status"],[[i["no"],i["date"],i["cn"],i["gstin"],i["state"],R(i["taxable"]),R(i["cgst"]),R(i["sgst"]),R(i["igst"]),R(i["total"]),i["status"]+(" ("+i["cn_no"]+")" if i["cn_no"] else "")] for i in rows(c,"select i.*,c.name cn,c.gstin,c.state from invoices i join customers c on c.id=i.customer_id where 1=1"+df+" order by i.id",*dt)])
    if n=="customerwise": return T(["Customer","Invoices","Taxable","Total"],[[r["name"],r["n"],R(r["t"]),R(r["g"])] for r in rows(c,"select c.name,count(*) n,sum(taxable) t,sum(total) g from invoices i join customers c on c.id=i.customer_id where status='active'"+df+" group by c.id",*dt)])
    if n=="productwise": return T(["Product","HSN","Qty","Taxable"],[[r["name"],r["hsn"],r["q"],R(r["t"])] for r in rows(c,"select it.name,l.hsn,sum(l.qty) q,sum(l.taxable) t from invoice_lines l join invoices i on i.id=l.invoice_id join items it on it.id=l.item_id where i.status='active'"+df.replace("date","i.date")+" group by l.item_id",*dt)])
    if n=="gst":
        return T(["Supply","HSN","Rate %","Taxable","CGST","SGST","IGST","Total tax"],[["Inter-state (IGST)" if r["ig"] else "Intra-state (CGST+SGST)",r["hsn"],r["rate"],R(r["t"]),R(r["cg"]),R(r["sg"]),R(r["ig"]),R(r["cg"]+r["sg"]+r["ig"])] for r in rows(c,"select l.hsn,l.rate,(l.igst>0) ig,sum(l.taxable) t,sum(l.cgst) cg,sum(l.sgst) sg,sum(l.igst) ig from invoice_lines l join invoices i on i.id=l.invoice_id where i.status='active'"+df.replace("date","i.date")+" group by l.hsn,l.rate,(l.igst>0)",*dt)])
    if n=="purchases": return T(["Date","Supplier","Item","Qty","Rate ₹","Amount ₹"],[[r["date"],r["supplier"],r["name"],f'{disp(r["qty"],r["factor"])} {r["unit"]}',R(r["rate"]),R(r["total"])] for r in rows(c,"select p.*,i.name,i.unit,i.factor from purchases p join items i on i.id=p.item_id where 1=1"+df+" order by p.id",*dt)])
    if n=="stock":
        out=[]
        for it in rows(c,"select * from items order by kind,id"):
            q=lambda w:c.execute(f"select coalesce(sum(qty),0) from ledger where item_id=? and {w}",(it["id"],)).fetchone()[0]; s,v=bal(c,it["id"]); f=it["factor"]
            out.append([it["name"],it["kind"],it["unit"],disp(q("doc_type='opening'"),f),disp(q("qty>0 and doc_type!='opening'"),f),disp(-q("qty<0"),f),disp(s,f),R(round(v*f/s)) if s else "0.00",R(v)])
        return T(["Item","Type","Unit","Opening","Receipts","Issues/Sales","Closing","Avg rate ₹","Value ₹"],out)
    if n=="ledger":
        out=[]
        for it in rows(c,"select * from items order by id"):
            run=0
            for r in rows(c,"select * from ledger where item_id=? order by id",it["id"]):
                run+=r["qty"]; out.append([r["ts"],it["name"],r["doc_type"],f'{r["doc_type"]}#{r["doc_id"]}',disp(r["qty"],it["factor"]),disp(run,it["factor"]),R(r["value"]),r["batch"],r["note"]])
        return T(["Time","Item","Source","Document","Qty (+/−)","Balance","Value ₹","Batch","Note"],out)
    if n=="production":
        out=[]
        for r in rows(c,"select * from runs order by id"):
            r=run_view(c,r)
            for l in r["lines"]: out.append([r["batch_no"],l["name"],l["planned_disp"]+" "+l["unit"],l["actual_disp"]+" "+l["unit"],f'{l["var_bp"]/100:+.2f}%',"FLAG" if l["flag"] else "ok",R(l["value"])])
            out.append([r["batch_no"],"Yield (good packets)",r["expected"],r["good"],f'{r["yield_bp"]/100:+.2f}%',"FLAG" if r["yield_flag"] else "ok",f'cost/packet ₹{r["cpp"]/100:.2f}; wastage {r["damaged"]} pouches'])
        return T(["Batch","Item","Planned","Actual","Variance","Status","Value / note"],out)
    if n=="outstanding": return T(["Invoice","Customer","Date","Total","Paid","Due","Age (days)","Bucket"],[[i["no"],i["cname"],i["date"],R(i["total"]),R(i["paid"]),R(i["due"]),i["age"],"0-30" if i["age"]<=30 else "31-60" if i["age"]<=60 else "61+"] for i in outstanding_rows(c) if i["due"]>0])
    if n=="payments": return T(["Time","Invoice","Customer","Mode","Amount ₹"],[[r["ts"],r["no"],r["name"],r["mode"],R(r["amount"])] for r in rows(c,"select p.*,i.no,c.name from payments p join invoices i on i.id=p.invoice_id join customers c on c.id=p.customer_id order by p.id")])
    if n=="audit": return T(["Time","User","Action","Ref","Detail"],[[r["ts"],r["user"],r["action"],r["ref"],r["detail"]] for r in rows(c,"select * from audit order by id desc limit 300")])
    raise E("Unknown report",404)
def csv_out(c,u,b,p,m):
    r=report(c,u,b,p,m); s=io.StringIO(); w=csv.writer(s); w.writerow(r["columns"]); w.writerows(r["rows"]); return (s.getvalue().encode("utf-8-sig"),"text/csv",f"{m[0]}.csv")

def pdf(lines):
    esc=lambda t:t.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
    ops="".join(f"BT /F{2 if bold else 1} {sz} Tf {x} {y} Td ({esc(t)}) Tj ET\n" for x,y,sz,t,bold in lines)
    objs=["<</Type/Catalog/Pages 2 0 R>>","<</Type/Pages/Kids[3 0 R]/Count 1>>","<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R/F2 6 0 R>>>>>>",
          f"<</Length {len(ops)}>>\nstream\n{ops}endstream","<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>","<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold>>"]
    out=b"%PDF-1.4\n"; off=[]
    for i,o in enumerate(objs): off.append(len(out)); out+=f"{i+1} 0 obj\n{o}\nendobj\n".encode("latin-1","replace")
    x=len(out); out+=f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()+b"".join(f"{o:010d} 00000 n \n".encode() for o in off)
    return out+f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{x}\n%%EOF".encode()
def inr(p):
    a,d=f"{Decimal(p)/100:.2f}".split("."); t=a[-3:]; a=a[:-3]
    while a: t=a[-2:]+","+t; a=a[:-2]
    return t.lstrip(",")+"."+d
def invoice_pdf(c,u,b,p,m):
    i=one(c,"select * from invoices where id=?",m[0]); cu=one(c,"select * from customers where id=?",i["customer_id"]); L=rows(c,"select l.*,it.name,it.unit,it.factor from invoice_lines l join items it on it.id=l.item_id where invoice_id=?",i["id"])
    o=[(40,800,18,"TAX INVOICE"+("  (CANCELLED - "+i["cn_no"]+")" if i["status"]!="active" else ""),1),(40,782,9,"Murukku Foods Pvt Ltd, Tiruchirappalli, Tamil Nadu  |  GSTIN 33AAACM0000A1Z1",0),
       (380,800,10,"Invoice No: "+i["no"],1),(380,786,10,"Date: "+i["date"],0),(40,750,10,"Bill to: "+cu["name"],1),(40,736,9,f'GSTIN: {cu["gstin"]}   State: {cu["state"]}',0),(40,724,9,"Place of supply: "+cu["state"]+(" (IGST)" if i["igst"] else " (CGST + SGST)"),0)]
    y=690
    for x,t in zip((40,75,255,315,375,425,480),("#","Item / HSN","Qty","Rate","Taxable","Tax %","Tax")): o.append((x,y,9,t,1))
    for n,l in enumerate(L,1):
        y-=18; tx=l["cgst"]+l["sgst"]+l["igst"]
        for x,t in zip((40,75,255,315,375,425,480),(str(n),f'{l["name"]} / {l["hsn"]}',f'{disp(l["qty"],l["factor"])} {l["unit"]}',inr(l["price"]),inr(l["taxable"]),str(l["rate"]),inr(tx))): o.append((x,y,9,t,0))
    y-=34
    for lab,v in (("Taxable value",i["taxable"]),("CGST",i["cgst"]),("SGST",i["sgst"]),("IGST",i["igst"]),("Total (Rs.)",i["total"])):
        if v or lab in("Taxable value","Total (Rs.)"): o+= [(340,y,10,lab,lab.startswith("Total")),(460,y,10,inr(v),lab.startswith("Total"))]; y-=16
    o.append((40,y-30,8,"Computer generated invoice. Amounts in Indian Rupees. Subject to Tiruchirappalli jurisdiction.",0)); return (pdf(o),"application/pdf",i["no"].replace("/","-")+".pdf")

def auth_login(c,u,b,p,m):
    r=one(c,"select * from users where username=? and pw=?",(b.get("username") or "").strip().lower(),pw(b.get("password") or ""))
    if not r: raise E("Wrong username or password.",401)
    t=secrets.token_hex(16); c.execute("insert into sessions values(?,?)",(t,r["id"])); return {"token":t,"user":{k:r[k] for k in("id","username","role","name")}}
A,AD,PR,AC,OW,SA="salesman admin production accountant owner".split()[0],"admin","production","accountant","owner","salesman"
ALL={SA,AD,PR,AC,OW}
ROUTES=[("POST",r"/api/login",None,auth_login),("GET",r"/api/me",ALL,lambda c,u,b,p,m:u),("GET",r"/api/items",ALL,lambda c,u,b,p,m:items_view(c)),("GET",r"/api/customers",ALL,customers),
 ("GET",r"/api/orders",{SA,AD},list_orders),("POST",r"/api/orders",{SA,AD},new_order),("POST",r"/api/orders/(\d+)/edit",{AD},edit_order),("POST",r"/api/orders/(\d+)/approve",{AD},approve),
 ("POST",r"/api/orders/(\d+)/reject",{AD},reject),("POST",r"/api/orders/(\d+)/invoice",{AD},invoice),("POST",r"/api/orders/(\d+)/dispatch",{AD},dispatch),("GET",r"/api/mysales",{SA},mysales),
 ("POST",r"/api/invoices/(\d+)/cancel",{AD},cancel_invoice),("GET",r"/api/invoices",{AD,AC},invoices_q),("GET",r"/api/invoices/(\d+)/pdf",{AD,AC,OW},invoice_pdf),("POST",r"/api/payments",{AD},pay),
 ("POST",r"/api/purchases",{AD,PR},purchase),("GET",r"/api/runs",{AD,PR,OW,AC},list_runs),("POST",r"/api/runs",{AD,PR},new_run),("POST",r"/api/runs/(\d+)/overheads",{AD,PR},overheads),
 ("GET",r"/api/ledger",{AD,PR,AC,OW},ledger_q),("GET",r"/api/dashboard",{AD,OW,PR},dashboard),("GET",r"/api/report/(\w+)",{AD,AC,OW},report),("GET",r"/api/report/(\w+)/csv",{AD,AC,OW},csv_out)]

class H(BaseHTTPRequestHandler):
    def log_message(s,*a): pass
    def send(s,code,body,ctype="application/json",extra=None):
        s.send_response(code); s.send_header("Content-Type",ctype); s.send_header("Content-Length",str(len(body)))
        for k,v in (extra or {}).items(): s.send_header(k,v)
        s.end_headers(); s.wfile.write(body)
    def handle_any(s,method):
        url=urlparse(s.path); path=url.path; p=parse_qs(url.query)
        if not path.startswith("/api/"):
            f=os.path.join(ROOT,"static","index.html" if path in("/","") else path.lstrip("/"))
            if not os.path.abspath(f).startswith(os.path.join(ROOT,"static")) or not os.path.isfile(f): f=os.path.join(ROOT,"static","index.html")
            ct={"html":"text/html","js":"text/javascript","css":"text/css","svg":"image/svg+xml","json":"application/json"}.get(f.rsplit(".",1)[-1],"application/octet-stream")
            return s.send(200,open(f,"rb").read(),ct+"; charset=utf-8")
        try:
            body=json.loads(s.rfile.read(int(s.headers.get("Content-Length") or 0)) or b"{}") if method=="POST" else {}
            for mth,pat,roles,fn in ROUTES:
                m=re.fullmatch(pat,path)
                if mth==method and m:
                    with LOCK, closing(conn()) as c:
                        u=None
                        if roles:
                            tok=(s.headers.get("Authorization","")[7:] or p.get("token",[""])[0]); u=one(c,"select u.* from sessions s join users u on u.id=s.user_id where token=?",tok)
                            if not u: raise E("Please sign in.",401)
                            if u["role"] not in roles: raise E("Your role cannot do this.",403)
                        res=fn(c,u,body,p,m.groups()); c.commit()
                    if isinstance(res,tuple): return s.send(200,res[0],res[1],{"Content-Disposition":f'inline; filename="{res[2]}"'})
                    return s.send(200,json.dumps(res).encode())
            raise E("Not found",404)
        except E as e: s.send(e.code,json.dumps({"error":e.msg}).encode())
        except Exception as e: s.send(500,json.dumps({"error":"Something went wrong: "+str(e)}).encode())
    def do_GET(s): s.handle_any("GET")
    def do_POST(s): s.handle_any("POST")
if __name__=="__main__":
    seed(); port=int(os.environ.get("PORT",8000)); print("Serving on",port); ThreadingHTTPServer(("0.0.0.0",port),H).serve_forever()
