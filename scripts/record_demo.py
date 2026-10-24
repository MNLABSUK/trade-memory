"""Record the Trade Memory demo: scripted Playwright run + macOS `say` voiceover."""
import json, subprocess, time, pathlib, shutil
from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/tm_demo_rec"); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir()
URL = "http://127.0.0.1:43151/"
SCENES = [
 ("title", "Trade Memory, by MN Labs. An agent that chases unpaid invoices for a small business, and shows its working before anything goes out."),
 ("header", "This is the Why desk. The header says Zetaris, live federated. Every figure on screen is a SQL query, run live through Zetaris across the operations database and the bank, email and contact files."),
 ("P1", "Five cases, five Why cards. Case one: Kestrel Self Storage. The invoice says unpaid, but the bank shows a payment with a reference that doesn't match. The card shows the evidence rows, the reasoning, and a confidence score, so nobody chases a client who has already paid."),
 ("P2", "Case two. Each card cites the exact rows it relies on. If a fact isn't in the data, the agent isn't allowed to say it."),
 ("P3", "Case three. Client facts come from Meterless H-MEM, the long-term memory layer. Things like who to contact, and how they prefer to be reached."),
 ("P4", "Case four. The proposal and the drafted email sit side by side, with the SQL that produced them."),
 ("P5", "Case five. The agent proposes a firm reminder. But I know this client is mid-dispute, so I'll reject it, with a note."),
 ("reject", "Rejecting stores my reason in H-MEM, and the card is revised straight away. The proposal for case five has changed, because the agent now remembers why I said no."),
 ("polish", "Back to case one. Polish asks NVIDIA Nemotron, through Nightshift, to rewrite the draft. The rewrite is citation-checked: if it drops or invents a fact, the original is kept."),
 ("approve", "Now I approve it. Approved means queued in the outbox, not sent. A human stays in the loop. Nothing leaves without a person pressing send."),
 ("end", "Trade Memory. Live data through Zetaris, memory with H-MEM, language from Nemotron, and a human gate on every message. MN Labs."),
]
CAPTIONS = {
 "title": "", "header": "Live Zetaris: every figure is a federated SQL query",
 "P1": "Why card: evidence · reasoning · confidence", "P2": "Every claim cites a source row",
 "P3": "Client facts from Meterless H-MEM", "P4": "Proposal + draft + the SQL behind it",
 "P5": "Human review: reject with a reason", "reject": "Rejection stored in H-MEM → proposal revised",
 "polish": "Polish via NVIDIA Nemotron (citation-checked)", "approve": "Approve = queued in outbox, never auto-sent",
 "end": "Trade Memory — MN Labs",
}
durs = {}
for k, text in SCENES:
    f = OUT / f"{k}.aiff"
    subprocess.run(["say", "-v", "Daniel", "-r", "165", "-o", str(f), text], check=True)
    d = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(f)],capture_output=True,text=True).stdout
    durs[k] = float(d)

TITLE = """<html><body style='margin:0;background:#0f172a;display:flex;align-items:center;justify-content:center;height:100vh;font-family:-apple-system,Helvetica'>
<div style='text-align:center;color:#f8fafc'><div style='font-size:64px;font-weight:700'>Trade Memory — MN Labs</div>
<div style='font-size:26px;color:#94a3b8;margin-top:18px'>Why cards on live Zetaris · H-MEM · Nemotron · human gate</div></div></body></html>"""
CAP_JS = """(t)=>{let c=document.getElementById('__cap');if(!c){c=document.createElement('div');c.id='__cap';
c.style.cssText='position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:rgba(15,23,42,.88);color:#fff;font:600 24px -apple-system,Helvetica;padding:10px 22px;border-radius:10px;z-index:99999;pointer-events:none';document.body.appendChild(c);}
c.textContent=t;c.style.display=t?'block':'none';}"""

starts = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    ctx = b.new_context(viewport={"width":1440,"height":810}, record_video_dir=str(OUT), record_video_size={"width":1440,"height":810})
    t0 = time.time()
    pg = ctx.new_page()
    def scene(k, action=None):
        starts[k] = time.time() - t0
        if action: action()
        if k != "title":
            pg.evaluate(CAP_JS, CAPTIONS[k])
        remain = durs[k] + 3.6 - (time.time() - t0 - starts[k])
        if remain > 0: pg.wait_for_timeout(int(remain*1000))
    def case(pid):
        pg.click(f"#caseList .case[data-id='{pid}']"); pg.wait_for_timeout(600)
    pg.set_content(TITLE); pg.wait_for_timeout(800)
    scene("title")
    pg.goto(URL); pg.wait_for_selector("#caseList .case"); pg.wait_for_timeout(1200)
    scene("header", lambda: pg.hover("#modeChip"))
    scene("P1", lambda: case("P1"))
    scene("P2", lambda: case("P2"))
    scene("P3", lambda: case("P3"))
    def p4():
        case("P4"); pg.mouse.wheel(0, 500); pg.wait_for_timeout(1500); pg.mouse.wheel(0, -500)
    scene("P4", p4)
    def p5():
        case("P5"); pg.fill("#note", "Client is mid-dispute over the unit damage — no firm reminder; offer a call first.")
    scene("P5", p5)
    def rej():
        pg.click("#rejectBtn"); pg.wait_for_timeout(2500)
    scene("reject", rej)
    def pol():
        case("P1"); pg.click("#polishBtn")
        pg.wait_for_selector("#toast:not(.hidden)", timeout=90000); pg.wait_for_timeout(1500)
    scene("polish", pol)
    def appr():
        pg.click("#approveBtn"); pg.wait_for_timeout(1500)
        pg.locator("#outbox").scroll_into_view_if_needed()
    scene("approve", appr)
    def end():
        pg.set_content(TITLE)
    scene("end", end)
    total = time.time() - t0
    vid = pg.video.path(); ctx.close(); b.close()
json.dump({"starts":starts,"durs":durs,"total":total,"video":str(vid)}, open(OUT/"timeline.json","w"), indent=1)
print(json.dumps({"total":total,"video":str(vid)}))
