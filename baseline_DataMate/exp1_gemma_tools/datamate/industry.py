"""Industry-specific computations (rulebook §6): motorbike repair, phone shop, mother & baby — called through the sx_* / dt_* / mb_* tools in tools.py."""
import calendar
import functools
import datetime as dt
import re

import pandas as pd

from . import parse as _P
from . import rules as R
from .period import norm

WEEKDAY = {"thu 2": 0, "thu hai": 0, "thu 3": 1, "thu ba": 1, "thu 4": 2, "thu tu": 2, "thu 5": 3, "thu nam": 3,
           "thu 6": 4, "thu sau": 4, "thu 7": 5, "thu bay": 5, "chu nhat": 6}


def _round(v):
    return int(v + 0.5)  # money rounded to the dong, half a dong rounds up


# ---------------- motorbike repair ----------------
def _plate(v):
    return str(v).split()[-1] if not _P.is_blank(v) else None


def _model_raw(v):
    return " ".join(str(v).split()[:-1]) if not _P.is_blank(v) else ""


def _mkey(m):
    return _P.key(m.replace("α", "alpha"))  # do not use norm(): its Telex fix breaks bike names ('wave' → 'ave')


def _models(L):
    """Merge the spellings of one bike model (case, abbreviations 'AB', 'Ex', extra number '110') → {key: canonical name}."""
    raw = L["vehicle"].map(_model_raw)
    cnt = raw.value_counts()
    keys = {}
    for m, n in cnt.items():
        keys.setdefault(_mkey(m), []).append((n, m))
    words = {k: [_P.key(w) for w in max(v)[1].replace("α", "alpha").split()] for k, v in keys.items()}
    initials = {k: "".join(w[0] for w in ws) for k, ws in words.items() if len(ws) > 1}

    def same(a, b):  # a is shorter than b: prefix, suffix, or initials of b's words
        return len(a) >= 2 and (b.startswith(a) or b.endswith(a) or initials.get(b) == a)

    root = {k: k for k in keys}
    def find(k):
        while root[k] != k:
            k = root[k]
        return k
    for a in keys:
        for b in keys:
            if len(a) < len(b) and same(a, b):
                root[find(b)] = find(a)
    fam = {}
    for k in keys:
        fam.setdefault(find(k), []).extend(keys[k])
    out = {}
    for v in fam.values():
        name = max(v)[1]  # canonical name = most frequent spelling
        for _, m in v:
            out[_mkey(m)] = name
    return out


def _warranty(L):
    note = L["note"].map(lambda v: norm(str(v)) if not _P.is_blank(v) else "") if "note" in L else ""
    jobs = L["jobs"].map(lambda v: norm(str(v)) if not _P.is_blank(v) else "") if "jobs" in L else ""
    return note.str.contains(r"bao hanh") | jobs.str.contains(r"^(bh|bao hanh)\b")


def _staff_names(shop, L):
    """Name used in the ledger ('a Đức', 'A.Đức') → full name in the mechanic list (matched by last name)."""
    S = shop.t.get("staff")
    if S is None or "staff_name" not in S:
        return L["staff_id"]
    last = {}
    for n in S["staff_name"].dropna():
        last.setdefault(norm(str(n)).split()[-1], []).append(str(n))
    def full(v):
        if _P.is_blank(v):
            return None
        w = norm(re.sub(r"[.]", " ", str(v))).split()
        c = last.get(w[-1]) if w else None
        return c[0] if c and len(c) == 1 else str(v)
    return L["staff_id"].map(full)


def _find_staff(shop, s):
    S = shop.t.get("staff")
    if S is None or "staff_name" not in S:
        return None
    for n in S["staff_name"].dropna():
        if norm(str(n)) in s:
            return str(n)
    return None


_JOBS = [(r"sua dien|lam dien", r"\b(sua|lam) dien\b"), (r"\bva (ruot|xe|lop)", r"^va\b"),
         (r"(dau|nhot) lap|thay lap|nhot hop so", r"\blap\b|hop so"), (r"rua xe", r"^rua( xe)?$"),
         (r"kim phun", r"kim phun"), (r"bugi|bu gi", r"bu ?gi"), (r"curoa|cu roa", r"cu ?roa"), (r"loc gio", r"loc gio"),
         (r"nuoc (lam )?mat", r"nuoc (lam )?mat"), (r"ac quy|thay binh", r"ac quy|\bbinh\b"), (r"bong den|den pha", r"bong den|den pha")]


# ---------------- motorbike repair: parameterized computations (sx_* tools) ----------------
def _num(v):
    return {"type": "number", "answer": v}


def _repair_L(shop, p):
    if "vehicle" not in shop.t["lines"]:
        raise R.Unanswerable("không phải sổ sửa xe")
    L = R.lines_in(shop, p).copy()
    L["tho"] = _staff_names(shop, L)
    L["bh"] = _warranty(L)
    return L


def _with_models(shop, L):
    models = _models(shop.t["lines"])
    L["model"] = L["vehicle"].map(lambda v: models.get(_mkey(_model_raw(v))))
    return models


def _match_model(models, text):
    mq, best, s2 = None, 0, _mkey(text)
    for k, name in models.items():  # match every spelling of a bike model, ignoring spaces ('Air Blade' ~ 'airblade')
        if len(k) >= 4 and k in s2 and len(k) > best:
            mq, best = name, len(k)
    return mq


def job_pattern(job):
    s = norm(job)
    return next((j for q, j in _JOBS if re.search(q, s)), None)


def repair_commission(shop, p, staff=None, mode=None):
    """Commission = mechanic's revenue × commission %. staff → that mechanic; mode table → table for all mechanics; top → highest mechanic."""
    S = shop.t.get("staff")
    if S is None or "commission" not in S:
        return None
    L = _repair_L(shop, p)
    pct = dict(zip(S["staff_name"], S["commission"].map(lambda v: _P.qty(v)[0])))
    rev = L.groupby("tho")["amount"].sum()
    com = pd.Series({n: _round(rev.get(n, 0) * pct[n] / 100) for n in pct})
    if staff:
        return _num(int(com[staff]))
    if mode == "table":
        rk = R._rank(com, None)
        return {"type": "table", "answer": {"columns": ["tho", "hoa_hong"], "rows": [[r.id, int(r.v)] for r in rk.itertuples()]}}
    if mode == "top":
        return {"type": "string", "answer": R._rank(com, 1)["id"].iloc[0]}
    return None


def repair_job_count(shop, p, jpat):
    """Number of bike visits that included job jpat (the 'Làm gì' cell lists several jobs); warranty tickets are not counted."""
    L = _repair_L(shop, p)
    if "jobs" not in L or not jpat:
        return None
    paid = L[~L["bh"]]
    parts = paid["jobs"].map(lambda v: [x.strip() for x in re.split(r"[,;+]", norm(str(v)))] if not _P.is_blank(v) else [])
    return _num(int(parts.map(lambda ps: any(re.search(jpat, x) for x in ps)).sum()))


def repair_avg_ticket(shop, p):
    paid = (L := _repair_L(shop, p))[~L["bh"]]
    return _num(_round(paid["amount"].sum() / len(paid))) if len(paid) else None


def repair_warranty(shop, p, as_percent=False):
    L = _repair_L(shop, p)
    n = int(L["bh"].sum())
    return {"type": "percent", "answer": R.share(n, int((~L["bh"]).sum()))} if as_percent else _num(n)


def repair_staff(shop, p, staff, metric):
    """metric revenue: the mechanic's money; turns: number of bike visits the mechanic handled."""
    L = _repair_L(shop, p)
    T = L[L["tho"] == staff]
    return _num(_round(T["amount"].sum())) if metric == "revenue" else _num(int(len(T))) if metric == "turns" else None


def repair_top_staff(shop, p, by):
    """by days: most hardworking (most working days); revenue: most money; turns: most visits."""
    L = _repair_L(shop, p)
    g = L.groupby("tho")
    v = {"days": lambda: g["order_date"].nunique(), "revenue": lambda: g["amount"].sum(), "turns": lambda: g.size()}.get(by)
    return {"type": "string", "answer": R._rank(v(), 1)["id"].iloc[0]} if v else None


def repair_top_model(shop, p):
    L = _repair_L(shop, p)
    _with_models(shop, L)
    return {"type": "string", "answer": R._rank(L.groupby("model")["amount"].sum(), 1)["id"].iloc[0]}


def repair_repeat_vehicles(shop, p, n=2):
    """Number of bikes (plates) that came n times or more; 'khách quen' (regular) = 2 times."""
    paid = (L := _repair_L(shop, p))[~L["bh"]]
    c = paid.assign(pl=paid["vehicle"].map(_plate)).groupby("pl").size()
    return _num(int((c >= n).sum()))


def repair_model_vehicles(shop, p, model):
    """Number of bikes (distinct plates) of one bike model."""
    L = _repair_L(shop, p)
    mq = _match_model(_with_models(shop, L), model)
    return _num(int(L.loc[L["model"] == mq, "vehicle"].map(_plate).nunique())) if mq else None


def repair_weekday_avg(shop, p, wd):
    """Average bike visits per weekday wd (0 = Monday … 6 = Sunday) in the period."""
    L = _repair_L(shop, p)
    days = [p.start + dt.timedelta(i) for i in range((p.end - p.start).days + 1)]
    nd = sum(d.weekday() == wd for d in days)
    n = int(L["order_date"].map(lambda d: d.weekday() == wd).sum())
    return _num(round(n / nd, 2)) if nd else None


def repair_ticket_count(shop, p):
    return _num(int(len(_repair_L(shop, p))))


# ---------------- phone shop ----------------
def _family(name):
    """Phone line = the part of the name before the capacity '…GB' (§6)."""
    m = re.search(r"\s\d+\s*GB\b", name, re.I)
    return name[:m.start()].strip() if m else name.strip()


def _brand(name):
    w = name.split()[0].lower()
    return "apple" if w == "iphone" else w


def _xdate(v):
    """Date cell in a hand ledger: Excel serial number or dd/mm/yyyy."""
    if _P.is_blank(v):
        return None
    if isinstance(v, (int, float)):
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.date()
    d, m, y = (int(x) for x in str(v).strip().split()[0].split("/"))
    return dt.date(y, m, d)


@functools.lru_cache(maxsize=64)
def _book(path, header):
    return pd.read_excel(path, sheet_name=None, dtype=object, header=header)


def _sheets_with(shop, *cols, header=0):
    """Sheets that have all the given column names, read directly from the shop's xlsx files (ledger tables the loader does not understand)."""
    from pathlib import Path
    return [df for f in sorted(Path(shop.folder).glob("*.xlsx")) for df in _book(str(f), header).values() if all(c in df.columns for c in cols)]


def _debt_book(shop, x):
    """Debt book + installment book at end of day x → DataFrame: cust, buy_date, remaining, overdue, due_n (installments due ≤ x)."""
    rows = []
    for df in _sheets_with(shop, "Nợ", "Đã trả", "Ngày trả"):
        df = df.assign(_k=df["Ghi chú"].ffill() if "Ghi chú" in df else df.index)
        for _, g in df.groupby("_k", sort=False):
            h = g.iloc[0]
            b = _xdate(h["Ngày"])
            if b is None or b > x:
                continue
            paid = sum(_P.money(a) or 0 for a, d in zip(g["Đã trả"], g["Ngày trả"]) if _xdate(d) and _xdate(d) <= x)
            rows.append({"cust": str(h["Khách"]).strip(), "buy_date": b, "remaining": (_P.money(h["Nợ"]) or 0) - paid, "overdue": 0, "due_n": 0})
    for df in _sheets_with(shop, "Số kỳ", "Góp/tháng", "Đã góp"):
        for _, g in df.groupby("STT", sort=False):
            h = g.iloc[0]
            b = _xdate(h["Ngày"])
            if b is None or b > x:
                continue
            total = (_P.money(h["Giá"]) or 0) - (_P.money(h["Trả trước"]) or 0)
            n, per, day = int(h["Số kỳ"]), _P.money(h["Góp/tháng"]), int(h["Hạn góp (ngày)"])
            paid = sum(_P.money(a) or 0 for a, d in zip(g["Đã góp"], g["Ngày góp"]) if _xdate(d) and _xdate(d) <= x)
            dues = []
            for i in range(1, n + 1):
                y, m = b.year + (b.month + i - 1) // 12, (b.month + i - 1) % 12 + 1
                dues.append(dt.date(y, m, min(day, calendar.monthrange(y, m)[1])))
            owed = lambda k: total if k >= n else k * per
            late = sum(d < x for d in dues)
            rows.append({"cust": str(h["Khách"]).strip(), "buy_date": b, "remaining": total - paid,
                         "overdue": max(0, owed(late) - paid), "due_n": sum(d <= x for d in dues), "inst": True})
    if not rows:
        raise R.Unanswerable("không có sổ nợ")
    D = pd.DataFrame(rows)
    D["ckey"] = D["cust"].map(_P.key)
    D["age"] = D["buy_date"].map(lambda d: (x - d).days)
    return D


def _phone_book(shop, x):
    if "imei" not in shop.t["lines"]:
        raise R.Unanswerable("không phải cửa hàng điện thoại")
    if shop.data_end and x > shop.data_end:
        return None
    return _debt_book(shop, x)


def _cust_in(D, s):
    return next((c for c in D["cust"].unique() if re.search(r"\b" + re.escape(norm(c)) + r"\b", s)), None)


def phone_installment(shop, x, what, customer=None):
    """Installment book up to end of day x. One customer: due_periods (installments already due) | remaining (still owed).
    Whole shop: remaining (still to pay) | overdue (overdue installment money) | overdue_customers (number of late payers)."""
    D = _phone_book(shop, x)
    if D is None:
        return None
    inst = D[D.get("inst", pd.Series(False, index=D.index)).fillna(False).astype(bool)]
    if customer:
        c = _cust_in(D, norm(customer))
        if c is None:
            return None
        C = inst[inst["cust"] == c]
        if what == "due_periods":
            return _num(int(C["due_n"].sum()))
        return _num(_round(C["remaining"].clip(lower=0).sum())) if what == "remaining" else None
    if what == "overdue_customers":
        return _num(int(inst.loc[inst["overdue"] > 0.5, "ckey"].nunique()))
    if what == "overdue":
        return _num(_round(inst["overdue"].sum()))
    return _num(_round(inst["remaining"].clip(lower=0).sum())) if what == "remaining" else None


def phone_debt(shop, x, what, buckets=None):
    """Debt + installment books still owed at end of day x. what: total (total money) | debtors (number of customers) | aging (by debt age, buckets [[lo, hi], …], hi None = and above)."""
    D = _phone_book(shop, x)
    if D is None:
        return None
    D = D[D["remaining"] > 0.5]
    if what == "aging":
        bk = [(int(lo), int(hi) if hi is not None else 10 ** 9) for lo, hi in buckets]
        return {"type": "list", "answer": [_round(D.loc[(D["age"] >= lo) & (D["age"] <= hi), "remaining"].sum()) for lo, hi in bk]}
    if what == "debtors":
        return _num(int(D["ckey"].nunique()))
    return _num(_round(D["remaining"].sum())) if what == "total" else None


_BRANDS = ("samsung", "apple", "xiaomi", "oppo", "nokia", "realme", "vivo")


def _phone_data(shop, p):
    """→ (Pr, O, L, phones) or None if the catalog has no product groups."""
    if "imei" not in shop.t["lines"]:
        raise R.Unanswerable("không phải cửa hàng điện thoại")
    Pr = shop.t.get("products")
    if Pr is None or "group" not in Pr:
        return None
    grp = dict(zip(Pr["pkey"], Pr["group"].map(lambda v: norm(str(v)))))
    O = R.orders_in(shop, p)
    L = R.lines_in(shop, p).copy()
    L["grp"] = L["pkey"].map(grp)
    L["fam"] = L["product_name"].map(lambda n: _family(str(n)))
    L["brand"] = L["product_name"].map(lambda n: _brand(str(n)))
    return Pr, O, L, L[L["grp"].isin(["may moi", "may cu"])]


def _find_family(Pr, s):
    fams = sorted({_family(str(n)) for n, g in zip(Pr["name"], Pr["group"].map(lambda v: norm(str(v)))) if g in ("may moi", "may cu")},
                  key=len, reverse=True)
    return next((f for f in fams if re.search(r"\b" + re.escape(norm(f)) + r"\b", s)), None)


def _find_brand(s):
    return next((b for b in _BRANDS if re.search(r"\b" + b + r"\b", s)), None) or ("apple" if re.search(r"\biphone\b", s) else None)


def phone_trade_in(shop, p, as_percent=False):
    """Money paid for trade-in phones (deducted from the order); as_percent → % of orders with a trade-in."""
    d = _phone_data(shop, p)
    if d is None or "trade_in" not in d[1]:
        return None
    O = d[1]
    if as_percent:
        return {"type": "percent", "answer": R.share(int((O["trade_in"].fillna(0) > 0).sum()), len(O))}
    return _num(_round(O["trade_in"].fillna(0).sum()))


def phone_total_due(shop, p, avg=False):
    """Amount the customer has to pay (after deducting trade-ins…); avg → average per order."""
    d = _phone_data(shop, p)
    if d is None or "total_due" not in d[1]:
        return None
    O = d[1]
    if avg:
        return _num(_round(O["total_due"].sum() / len(O))) if len(O) else None
    return _num(_round(O["total_due"].sum()))


def phone_warranty(shop, p, today, what):
    """what: count (warranty visits in the period) | pct_sold (% warranty visits / phones sold) | top_model (phone model with most warranty visits)
    | sold_seen (phones sold in the period that came in for warranty up to today, by IMEI)."""
    d = _phone_data(shop, p)
    W = shop.t.get("warranties")
    if d is None or W is None:
        return None
    phones = d[3]
    if what == "sold_seen":
        sold = {i.strip() for v in phones["imei"].dropna() for i in str(v).split("/") if i.strip()}
        seen = set(W.loc[W["warranty_date"].map(lambda x: x is not None and x <= today), "imei"].dropna().astype(str).str.strip())
        return _num(len(sold & seen))
    Wp = W[W["warranty_date"].map(lambda x: x is not None and p.start <= x <= p.end)]
    if what == "pct_sold":
        return {"type": "percent", "answer": R.share(len(Wp), phones["qty"].sum())}
    if what == "top_model":
        v = Wp.groupby("model").size()
        return {"type": "string", "answer": R._rank(v, 1)["id"].iloc[0]} if len(v) else None
    return _num(int(len(Wp))) if what == "count" else None


def phone_top_family(shop, p, k=None):
    """Best-selling phone line (by units); k → list of k lines."""
    d = _phone_data(shop, p)
    if d is None:
        return None
    rk = R._rank(d[3].groupby("fam")["qty"].sum(), k or 1)
    return {"type": "list", "answer": rk["id"].tolist()} if k else {"type": "string", "answer": rk["id"].iloc[0]}


def phone_top_in_group(shop, p, group):
    """Best-selling phone in the new-phone group (group new) or used-phone group (old)."""
    d = _phone_data(shop, p)
    if d is None:
        return None
    L = d[2]
    v = L[L["grp"] == ("may moi" if group == "new" else "may cu")].groupby("product_name")["qty"].sum()
    return {"type": "string", "answer": R._rank(v, 1)["id"].iloc[0]}


def phone_share(shop, p, what, brand=None):
    """what brand_units: % of phones sold that are brand `brand`; new_revenue: % of phone revenue that is new phones."""
    d = _phone_data(shop, p)
    if d is None:
        return None
    phones = d[3]
    if what == "brand_units" and (b := _find_brand(norm(brand or ""))):
        return {"type": "percent", "answer": R.share(phones.loc[phones["brand"] == b, "qty"].sum(), phones["qty"].sum())}
    if what == "new_revenue":
        return {"type": "percent", "answer": R.share(phones.loc[phones["grp"] == "may moi", "amount"].sum(), phones["amount"].sum())}
    return None


def phone_avg_price(shop, p, old_only=False):
    """Average selling price per phone (old_only → used phones only)."""
    d = _phone_data(shop, p)
    if d is None:
        return None
    P2 = d[3][d[3]["grp"] == "may cu"] if old_only else d[3]
    return _num(_round(P2["amount"].sum() / P2["qty"].sum())) if P2["qty"].sum() else None


def phone_units(shop, p, cond=None, family=None, brand=None):
    """Number of phones sold; cond old/new filters used/new; family (phone line) or brand to filter further."""
    d = _phone_data(shop, p)
    if d is None:
        return None
    X = d[3]
    if cond in ("old", "new"):
        X = X[X["grp"] == ("may cu" if cond == "old" else "may moi")]
    if family:
        f = _find_family(d[0], norm(family))
        if f is None:
            return None
        X = X[X["fam"].map(norm) == norm(f)]
    elif brand:
        b = _find_brand(norm(brand))
        if b is None:
            return None
        X = X[X["brand"] == b]
    return _num(int(X["qty"].sum()))


# ---------------- mother & baby: invoice side lines, size/stage/brand catalog, member customers ----------------
def _mb_cache(shop):
    if not hasattr(shop, "_mb"):
        cat = _sheets_with(shop, "Số / Size", "Hãng", "Tên hàng")
        extra = []
        for df in _sheets_with(shop, "HĐ", "TT", "Tên hàng", header=1):
            x = df[df["Tên hàng"].astype(str).str.match(r"^(Voucher|Dùng \d+ điểm|Phí ship)$")]
            extra.append(x[["HĐ", "Tên hàng", "TT"]])
        mem = _sheets_with(shop, "Tên KH", "Ngày đăng ký")
        shop._mb = (cat[0] if cat else None, pd.concat(extra) if extra else None, mem[0] if mem else None)
    return shop._mb


def _mb_ready(shop):
    """→ (catalog, side lines, members) if this is a mother & baby ledger, else None."""
    if not re.search(r"so / size|voucher|dung <n> diem", norm(shop.readme["text"])):
        return None
    r = _mb_cache(shop)
    return r if r[0] is not None else None


def _mb_lines(shop, p, cat):
    C = cat.assign(pkey=cat["Tên hàng"].map(_P.key), grp=cat["Nhóm"].map(lambda v: norm(str(v))),
                   size=cat["Số / Size"].map(lambda v: norm(str(v)) if not _P.is_blank(v) else None), brand=cat["Hãng"].map(lambda v: norm(str(v))))
    return C, R.lines_in(shop, p).merge(C[["pkey", "grp", "size", "brand", "Hãng"]], on="pkey", how="left")


def _qty(v):
    return int(v) if float(v).is_integer() else round(float(v), 2)


def mb_new_members(shop, p):
    """Number of customers who registered as new members in the period."""
    r = _mb_ready(shop)
    if r is None or r[2] is None:
        return None
    d = r[2]["Ngày đăng ký"].map(lambda v: _P.date(v)[0])
    return _num(int(d.map(lambda x: x is not None and p.start <= x <= p.end).sum()))


def mb_extra(shop, p, kind):
    """Total of invoice side lines in the period: kind voucher | points (points redeemed) | ship (shipping fee)."""
    r = _mb_ready(shop)
    if r is None or r[1] is None or kind not in ("voucher", "points", "ship"):
        return None
    ids = set(R.orders_in(shop, p)["order_id"])
    E = r[1][r[1]["HĐ"].isin(ids)]
    pat = {"voucher": "Voucher", "points": "điểm", "ship": "Phí ship"}[kind]
    return _num(_round(abs(E.loc[E["Tên hàng"].astype(str).str.contains(pat), "TT"].map(_P.money).sum())))


def mb_diaper(shop, p, size=None, brand=None, as_percent=False):
    """Diapers sold (base unit) of one size (NB, S, M, L, XL, XXL) OR one brand; as_percent → % of all diapers."""
    r = _mb_ready(shop)
    if r is None or bool(size) == bool(brand):
        return None
    C, L = _mb_lines(shop, p, r[0])
    B = L[L["grp"] == "bim ta"]
    if size:
        sel = B[B["size"] == "size " + re.sub(r"^size ", "", norm(size))]
    else:
        br = next((b for b in C.loc[C["grp"] == "bim ta", "brand"].unique() if re.search(r"\b" + re.escape(b) + r"\b", norm(brand))), None)
        if br is None:
            return None
        sel = B[B["brand"] == br]
    v = sel["qty_base"].sum()
    return {"type": "percent", "answer": R.share(v, B["qty_base"].sum())} if as_percent else _num(_qty(v))


def mb_milk_qty(shop, p, stage):
    """Number of cans of formula milk stage `stage` (1, 2, 3, 4…) sold."""
    r = _mb_ready(shop)
    if r is None:
        return None
    _, L = _mb_lines(shop, p, r[0])
    return _num(_qty(L.loc[(L["grp"] == "sua bot") & (L["size"] == f"so {stage}"), "qty_base"].sum()))


def mb_milk_top_brand(shop, p, stage, by="qty"):
    """Best-selling formula milk brand for stage `stage` (by qty cans | revenue)."""
    r = _mb_ready(shop)
    if r is None:
        return None
    _, L = _mb_lines(shop, p, r[0])
    X = L[(L["grp"] == "sua bot") & (L["size"] == f"so {stage}")]
    return {"type": "string", "answer": R._rank(X.groupby("Hãng")["amount" if by == "revenue" else "qty_base"].sum(), 1)["id"].iloc[0]}


