"""Runs the section-5 benchmark end to end over HTTP and asserts every expected number.  python tests/test_benchmark.py"""
import os,sys,json,tempfile,threading,urllib.request,urllib.error
os.environ["DB_PATH"]=os.path.join(tempfile.mkdtemp(),"t.db"); sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
server.seed(); srv=server.ThreadingHTTPServer(("127.0.0.1",0),server.H); threading.Thread(target=srv.serve_forever,daemon=True).start(); URL=f"http://127.0.0.1:{srv.server_port}"
def call(path,tok=None,body=None):
    r=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,headers={"Authorization":"Bearer "+(tok or "")})
    try: return json.loads(urllib.request.urlopen(r).read())
    except urllib.error.HTTPError as e: return {"error":json.loads(e.read())["error"]}
T={u:call("/api/login",body={"username":u,"password":"demo123"})["token"] for u in("sales_a","sales_b","admin","production")}
stock=lambda n:{i["name"]:i for i in call("/api/items",T["admin"])}[n]["stock"]
def ok(name,got,exp): print(("PASS" if str(got)==str(exp) else "FAIL"),name,got,"(expected",exp,")"); assert str(got)==str(exp)
call("/api/purchases",T["production"],{"item_id":1,"qty":60,"rate":45,"supplier":"Sri Flour Mills"})
run=call("/api/runs",T["production"],{"product_id":6,"batches":1,"good":188,"damaged":6,"actual":{"1":40,"2":10.5,"3":1.2,"5":9}})
ok("flour",stock("Flour"),120); ok("oil",stock("Cooking oil"),"19.5"); ok("pouches",stock("200 g pouch"),306); ok("FG after run",stock("Murukku 200 g"),238)
ok("yield var %",run["yield_bp"]/100,-6.0); oil=[l for l in run["lines"] if l["name"]=="Cooking oil"][0]; ok("oil var %",oil["var_bp"]/100,5.0); ok("oil flagged",oil["flag"],True)
call(f"/api/runs/{run['id']}/overheads",T["production"],{"labour":1200,"power":600}); r=call("/api/runs",T["admin"])[0]; ok("cost/packet ₹",f"{r['cpp']/100:.2f}",31.14)
o=call("/api/orders",T["sales_a"],{"customer_id":1,"lines":[{"item_id":6,"qty":150}]}); call(f"/api/orders/{o['id']}/approve",T["admin"],{}); inv=call(f"/api/orders/{o['id']}/invoice",T["admin"],{}); print(call(f"/api/orders/{o['id']}/dispatch",T["admin"],{}).get("error"))
ok("FG after dispatch",stock("Murukku 200 g"),88); I=call("/api/invoices",T["admin"])[0]; ok("taxable",I["taxable"],750000); ok("cgst",I["cgst"],18750); ok("sgst",I["sgst"],18750); ok("total",I["total"],787500)
b=call("/api/orders",T["sales_b"],{"customer_id":2,"lines":[{"item_id":6,"qty":120}]}); ok("B blocked",call(f"/api/orders/{b['id']}/approve",T["admin"],{}).get("error","")[:9],"Stock doe"); ok("B shortage",b["lines"][0]["short"],32)
bb=call(f"/api/orders/{b['id']}/approve",T["admin"],{"force":1}); call(f"/api/orders/{b['id']}/invoice",T["admin"],{}); I2=call("/api/invoices",T["admin"])[1]; ok("B IGST",I2["igst"],int(I2["taxable"]*0.05))
print(call(f"/api/orders/{b['id']}/dispatch",T["admin"],{})["error"])
call("/api/payments",T["admin"],{"invoice_id":I["id"],"amount":4000}); ok("A outstanding",[i for i in call("/api/invoices",T["admin"]) if i["id"]==I["id"]][0]["due"],387500)
ok("pdf",urllib.request.urlopen(urllib.request.Request(URL+f"/api/invoices/{I['id']}/pdf?token="+T["admin"])).read()[:4],b"%PDF")
for n in("sales","gst","stock","ledger","production","outstanding","purchases","customerwise","productwise"): assert call(f"/api/report/{n}",T["admin"])["rows"] is not None
# --- extra checks: offline retry safety, more products, credit note, audit
o1=call("/api/orders",T["sales_a"],{"client_id":"offline-1","customer_id":1,"lines":[{"item_id":12,"qty":10}]}); o2=call("/api/orders",T["sales_a"],{"client_id":"offline-1","customer_id":1,"lines":[{"item_id":12,"qty":10}]}); ok("offline retry is idempotent",o1["id"],o2["id"])
ok("four sellable products",len([i for i in call("/api/items",T["admin"]) if i["kind"]=="fg"]),4)
r2=call("/api/runs",T["production"],{"product_id":12,"batches":1,"good":190,"damaged":4,"actual":{"7":20,"1":15,"2":8,"3":1.5,"5":10}}); ok("Mixture run saved",r2.get("good"),190); ok("Mixture FG stock",stock("Mixture 200 g"),310)
call(f"/api/invoices/{I['id']}/cancel",T["admin"],{}); ok("credit note returns stock",stock("Murukku 200 g"),238)
ok("sales register shows CN","CN/" in json.dumps(call("/api/report/sales",T["admin"])),True); ok("audit trail logged",len(call("/api/report/audit",T["admin"])["rows"])>8,True)
print("ALL BENCHMARK CHECKS PASSED")
