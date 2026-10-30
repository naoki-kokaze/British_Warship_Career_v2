"""
v2本評価用「新しい艦」の選定（2026-10-08）

入力（読み取りのみ）:
  ../outputs/winfield_text/Winfield_*.txt  … Winfield_OCR PDF（Dropbox、sources/winfield_ocr）から pdftotext で抽出した全文。Git対象外
  ../sources/v1/strata/*.xlsx               … 開発用269隻（除外に使う）
出力:
  ../sources/eval_v2/strata/<Prefix>.xlsx   … 選定艦（試し・本評価・予備）。v1と同じ列構成で、既存の規則パイプラインにそのまま入る
  ../outputs/eval_v2/eval_v2_selection.csv  … 選定一覧（原文なし）
  ../outputs/eval_v2/eval_v2_pool_counts.csv … 系統・層ごとの候補数

方針:
- 項目の切り出しは見出し行（艦名＋造船所など）の発見的規則による。元のserial_noは完全には再現できない
  （開発用269隻で照合すると位置が数件ずれる）ため、新しい艦のIDは 9000＋本スクリプトでの通し番号 とし、
  開発用IDと衝突しないようにする（例 SBS_9123）
- 候補は建造（取得）と最期の記述がある60〜6000字の項目（real()の注を参照）。試しの5隻は固定（TRIAL_FIXED）
- 除外：開発用269隻（パイロット32隻を含む）、模範例 SL2_0027 Vanguard
- 系統は計画メモ§5の6系統案（2026-10-08）。乱数シード固定
"""
import os, csv, random
import re,openpyxl,collections,json,unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.join(HERE, "../outputs/winfield_text/")
STRATA = os.path.join(HERE, "../sources/v1/strata/")
KEY=re.compile(r"^\s*(As built|Ord|Dimensions & tons|Dimensions|Conversion ord|Tonnage as|K: ?\d|Purchased|Taken|Captured|Commissioned|First cost)\b")
NOTSTART=re.compile(r"^(As built|Ord|Dimensions|Men|Guns|Machinery|Armour|Commissioned|Recommissioned|First cost|Tonnage|Draught|BRITISH WARSHIPS|Both|The|All|This|These|She|They|In|On|Her|His|Its|Later|Sold|BU|Paid|Fitted|Completed|Converted|Became|Renamed|Lent|Used|Hulked|Wrecked|Foundered|Taken|Captured|Purchased|Designed|Built|Approved|Ordered|Laid|Launched|With|From|To|At|By|For|Of|As|An?|And|But|Two|Three|Four|Six|Under|Re|Cut|Rebuilt)\b")
JUNK=lambda s: len(s.strip())<6
def is_head(L,i):
    l=L[i]
    if re.match(r"^[A-Z][A-Z'\-]{2,}(?: [A-Z][A-Z'\-]+)*\s+(Purchased \d|1 ?\d ?\d ?\d\s?-|\[ex-|\(ex-|ex-)",l): return True   # 購入艦など大文字見出しの単独項目
    if not l.strip() or NOTSTART.match(l) or KEY.match(l): return False
    m=re.match(r"^([A-Z][A-Za-z'\.\-]+)(?:\s+(\S+)|\s*$)",l)   # 先頭語の直後は空白か行末（「Ordinary).」のような断片を除く）
    if not m: return False
    w1,w2=m.group(1),m.group(2) or ""
    craft=w1.rstrip(".") in ("MF","MV","YC")   # 艀などの番号名（MF. 109 など）
    if w1.endswith((".",";",",")) and w1 not in ("St.","Mt.") and not craft: return False   # 文の途中の行（「Portsmouth. Re-engined…」など）
    if w2.startswith("Dyd"): return False   # 「Chatham Dyd. BU…」のような経歴の続きの行
    if re.match(r"^\d{1,2}\.\d",w2) and not craft: return False   # 「Resolute 7.3.1850.」のような改名の折り返し
    if re.search(r"under (Capt|Cmdr|Lieut)|[Pp]aid off|Re-?engined|Recommissioned",l): return False
    if re.match(r"^[A-Z]{2,}$",w1) and re.search(r"\b(Class|Group|guns|design)\b",l) and not re.search(r"\[ex-|Purchased \d|\d{4}-\d{2}",l): return False
    if w2 and not re.match(r"^[A-Z0-9\[\(]",w2): return False
    nxt=[x for x in L[i+1:i+8] if not JUNK(x)][:2]
    if nxt and KEY.match(nxt[0]): return True
    if re.search(r"Dyd|Sbdg|Shipyard|& Sons?|Bros\b|& Co\b|\[ex-|\(ex-|\(French|\(Danish|\(Dutch|\(Spanish|\(American|Purchased \d{4}",l) and not l.rstrip().endswith((";",",")):
        return True
    return False
PDF={"SL1":"1_firstRate","SL2":"2_secondRate","SL3":"3_thirdRate","SL4":"4_fourthRate","SF5":"5_fifthRate","SC6":"6_sixthRate","SSL":"7_sloop","SBS":"8_brigSloop","SCS":"9_cutterSchooner","SM":"10_miscSailingVessel","SCSL":"12_screwSloop","SCGVG":"13_screwGunvessel","SCM":"14_miscScrewVessel"}
def load(n): return open(T+f"Winfield_{n}.txt",encoding="utf-8").read().split("\n")
def find_line(L,pat):
    for i,l in enumerate(L):
        if l.strip()==pat: return i
    raise ValueError(pat)
def sections():
    out={}
    for p,n in PDF.items():
        L=load(n); out[p]=(n,L,0,len(L))
    L=load("11_steamPaddleVessel")
    a,b,c,d=[find_line(L,x) for x in ["PADDLE FRIGATES","PADDLE SLOOPS","PADDLE GUNVESSELS","PADDLE PACKETS"]]
    n="11_steamPaddleVessel"
    out.update({"PSPV":(n,L,0,a),"PF":(n,L,a,b),"PSL":(n,L,b,c),"PGV":(n,L,c,d),"PM":(n,L,d,len(L))})
    L=load("15_firstIronclads"); n="15_firstIronclads"
    a=find_line(L,"Armoured Iron Frigates (Broadside Ironclads)")
    b=find_line(L,"Armoured Wooden Cruisers (Broadside or Central Battery Ironclads)")
    c=find_line(L,"Armoured Coastal Defence Ships (Turret Ironclads)")
    out.update({"AIF":(n,L,a,b),"AWC":(n,L,b,c),"ACD":(n,L,c,len(L))})
    return out
def norm(s): return re.sub(r"[^a-z]","",unicodedata.normalize("NFKD",s or "").lower())
CLASSHEAD=re.compile(r"^[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)*\s+(Class|Group|\d+ guns|Steam|Wooden|Iron)\b")
PAGEJUNK=re.compile(r"^(BRITISH WARSHIPS IN THE AGE OF SAIL|[\d\s%•·\-–]*$|[A-Z]?\d{1,3}%$)")
FATE=re.compile(r"\b(SU at|Sold|BU|Broken up|Wrecked|Foundered|Lost|Hulked|Expended|Burnt|Transferred|Taken to pieces|Scuttled|Deleted)\b")
def clean(lines):
    out=[]
    for k,l in enumerate(lines):
        l=re.sub(r"[\x00-\x08\x0b-\x1f]","",l)
        if k>0 and (CLASSHEAD.match(l) or re.match(r"^\([A-Z]\) |^[A-Z][A-Z ,&\-]{5,}$|^\d{4} Programme|^[\dA-Z][\dA-Z\-]{2,} TYPE\b",l)): break   # 次のクラス説明・節見出し・建造計画見出しで打ち切り      # 次のクラス説明に入ったら打ち切り
        if PAGEJUNK.match(l.strip()) or len(l.strip())<3: continue
        out.append(l)
    # 経歴の後に次のクラスの説明・諸元が続いていたら、最後の「最期」の行で打ち切る
    career=None
    for k,l in enumerate(out):
        if career is None and re.search(r"Commissioned|Recommissioned|Fitted|In Ordinary|Laid up|[Pp]aid off|Sold|BU\b",l): career=k
        if career is not None and k>career and re.match(r"^(Dimensions|Men:|Guns:|Machinery:|Armour:)",l):
            fates=[j for j in range(career,k) if FATE.search(out[j])]
            if fates:
                j=fates[-1]
                if not out[j].rstrip().endswith(".") and j+1<k: j+=1   # 最期の文が次の行に折り返している
                out=out[:j+1]
            else:
                out=out[:k]
            break
    else:
        # 最期の文の後に経歴のない文章（次のクラスの説明など）が続く場合も打ち切る
        fates=[j for j in range(career or 0,len(out)) if FATE.search(out[j])] if career is not None else []
        if fates:
            j=fates[-1]
            if not out[j].rstrip().endswith((".",")")) and j+1<len(out): j+=1
            rest=out[j+1:]
            if rest and not any(re.search(r"\d{1,2}\.\d{4}|Commissioned|[Pp]aid off",x) for x in rest):
                out=out[:j+1]
    return "\n".join(out).strip()
TWOWORD={"San","Santa","Santo","Royal","Prince","Princess","Black","Frederick","North","Tre","Tree","Sans","Lord","Queen","King","Duke","Great","Grand","Sir","St","St.","Fair","New","Old","Red","Wild","Rose","Golden","Lady","Port","Cape","Mont","Le","La","Les","El"}
def entries(p,sec):
    n,L,a,b=sec
    heads=[i for i in range(a,b) if is_head(L,i)]
    E=[]
    for k,i in enumerate(heads):
        j=heads[k+1] if k+1<len(heads) else b
        w=L[i].strip().split()
        name=" ".join(w[:2]) if len(w)>1 and w[0] in TWOWORD else w[0]   # 艦名は原則1語（2語名は先頭語で判定）
        E.append(dict(prefix=p,pdf=n,seq=k+1,line=i+1,head=L[i].strip()[:120],name=name.strip(),text=clean(L[i:j])))
    return E
def dev():
    D={}
    for f in PDF.keys()|{"PSPV","PF","PSL","PGV","PM","AIF","AWC","ACD"}:
        ws=openpyxl.load_workbook(STRATA+f+".xlsx").worksheets[0]
        D[f]=[(int(r[3]),r[5],(r[7] or "").split("\n")[0]) for r in ws.iter_rows(min_row=2,values_only=True) if r[3]]
    return D

GROUPS = {
    "A": ("帆走・大型", ["SL1", "SL2", "SL3", "SL4", "SF5", "SC6"]),
    "B": ("帆走・小型", ["SBS", "SSL", "SCS"]),
    "C": ("外輪", ["PF", "PGV", "PSL", "PSPV"]),
    "D": ("スクリュー", ["SCGVG", "SCSL"]),
    "E": ("装甲艦", ["ACD", "AIF", "AWC"]),
    "F": ("雑役・補助", ["SM", "PM", "SCM"]),
}
SEED = 20261008
N_MAIN, N_RESERVE = 7, 4
# 試しの判定5隻は固定（2026-10-08確定）。IDは切り出し規則で変わりうるので (層, 艦名) で指定。
# 当初のPM Mulletは経歴がほぼなく試しに不向きなため除外した（ユーザー判断）
TRIAL_FIXED = {"A": ("SF5", "dartmouth"), "B": ("SBS", "rinaldo"), "C": ("PSPV", "meteor"),
               "D": ("SCSL", "rapid"), "F": ("SM", "resolute")}
OUT_STRATA = os.path.join(HERE, "../sources/eval_v2/strata")
OUT = os.path.join(HERE, "../outputs/eval_v2")


def real(e):
    """候補の条件：建造（または取得）と最期の記述があり、60〜6000字（2026-10-08 緩和）。
    経歴の記述は求めない。当初は経歴も必須にしていたが、開発用Fの29%しか通らず、
    短い項目（艀・係留艇など）が落ちて標本が偏るため緩めた（緩和後、開発用の通過率はF 87%、A〜E 85〜100%）"""
    t = e["text"]
    build = re.search(r"\b(Ord|L|K):\s?\d|Purchased|Taken|Captured|\[ex-|\(French|built", t)
    fate = re.search(r"\b(Sold|BU|Broken up|Wrecked|Foundered|Lost|Hulked|Expended|Burnt|Transferred|Target|Taken to pieces|Scuttled|Became|Lent|Deleted|Renamed)\b", t)
    return bool(build and fate) and 60 < len(t) < 6000


def class_of(sec, line):
    n, L, a, b = sec
    for i in range(line - 2, a - 1, -1):
        m = re.match(r"^((?:[A-Z][A-Z'\-]+)(?: [A-Z][A-Z'\-]+)*)\s+(Class|Group|\d|Steam|Wooden|Iron|Purchased|Built|Isaac|Sir|Edward|Oliver)", L[i])
        if m and m.group(1) not in ("BRITISH", "MLR", "TC", "BU", "AO", "YC"):
            return m.group(1)
    return None


def main():
    S, D = sections(), dev()
    genre = {}
    for p in S:
        ws = openpyxl.load_workbook(STRATA + p + ".xlsx").worksheets[0]
        genre[p] = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    pool, counts = {}, []
    for g, (gname, ps) in GROUPS.items():
        pool[g] = []
        for p in ps:
            E = entries(p, S[p])
            devh = {norm(f)[:25] for _, _, f in D[p]}
            R = [e for e in E if real(e)]
            C = [e for e in R if norm(e["head"])[:25] not in devh
                 and not (p == "SL2" and e["name"].startswith("Vanguard"))]
            for e in C:
                e.update(group=g, id=f"{p}_{9000 + e['seq']:04d}", serial=9000 + e["seq"],
                         cls=None if re.match(r"^[A-Z][A-Z'\-]{2,}\b", e["head"]) else class_of(S[p], e["line"]))   # 大文字見出しの単独項目はクラスなし（v1と同じ）
            pool[g] += C
            counts.append(dict(group=g, group_name=gname, prefix=p, segmented=len(E),
                               plausible=len(R), candidates=len(C), dev=len(D[p])))
    rng = random.Random(SEED)
    sel = []
    for g in GROUPS:
        cand = sorted(pool[g], key=lambda e: e["id"])
        rng.shuffle(cand)
        k = 0
        if g in TRIAL_FIXED:
            hit = [e for e in cand if (e["prefix"], norm(e["name"])) == TRIAL_FIXED[g]]
            assert len(hit) == 1, (g, TRIAL_FIXED[g], len(hit))
            sel.append((hit[0], "trial"))
            cand = [e for e in cand if e is not hit[0]]
        sel += [(e, "main") for e in cand[:N_MAIN]]
        sel += [(e, "reserve") for e in cand[N_MAIN:N_MAIN + N_RESERVE]]
    os.makedirs(OUT_STRATA, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    by_p = collections.defaultdict(list)
    for e, role in sel:
        by_p[e["prefix"]].append(e)
    for p, es in by_p.items():
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = p
        ws.append(["Genre", "Prefix", "strata_no", "serial_no", "CLASS", "Name", "ID", "text"])
        for k, e in enumerate(sorted(es, key=lambda e: e["serial"]), 1):
            ws.append([genre[p], p, k, e["serial"], e["cls"], e["name"], f"myData:{e['id']}", e["text"]])
        wb.save(os.path.join(OUT_STRATA, p + ".xlsx"))
    with open(os.path.join(OUT, "eval_v2_selection.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "role", "group", "group_name", "prefix", "class", "name", "pdf", "pdf_line", "chars"])
        for e, role in sorted(sel, key=lambda x: (["trial", "main", "reserve"].index(x[1]), x[0]["group"], x[0]["id"])):
            w.writerow([e["id"], role, e["group"], GROUPS[e["group"]][0], e["prefix"], e["cls"], e["name"],
                        e["pdf"], e["line"], len(e["text"])])
    with open(os.path.join(OUT, "eval_v2_pool_counts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(counts[0])); w.writeheader(); w.writerows(counts)
    print(f"selected {len(sel)} ships ->", OUT_STRATA)


if __name__ == "__main__":
    main()
