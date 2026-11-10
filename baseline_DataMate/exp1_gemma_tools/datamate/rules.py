"""Rulebook rules written as functions. Each function returns a value or raises Unanswerable."""
from .period import Period


class Unanswerable(Exception):
    pass


VALID = ("hoan_thanh", "dang_giao")  # §1: revenue orders = not cancelled, not returned


def _check_range(shop, p: Period):
    """§7: the period lies entirely outside the data range → cannot be answered."""
    if shop.data_start is None:  # order date unreadable: a loading error, not missing data → abstain
        raise ValueError("shop không có ngày đơn")
    if p.end < shop.data_start or p.start > shop.data_end:
        raise Unanswerable(f"kỳ {p.start}..{p.end} ngoài dữ liệu {shop.data_start}..{shop.data_end}")


def orders_in(shop, p: Period, valid_only=True):
    _check_range(shop, p)
    O = shop.t["orders"]
    m = O["order_date"].map(lambda d: d is not None and p.start <= d <= p.end)
    O = O[m]
    return O[O["status"].isin(VALID)] if valid_only else O


def revenue(shop, p):
    return int(round(orders_in(shop, p)["revenue_lines"].sum()))


def order_count(shop, p):
    return int(len(orders_in(shop, p)))


def avg_order_value(shop, p, cust_group=None):
    O = orders_in(shop, p)
    if cust_group:
        O = O[order_cust_group(shop, O) == _P.key(cust_group)]
    if not len(O):
        raise Unanswerable("không có đơn")
    v = O["revenue_lines"].sum() / len(O)
    return int(v + 0.5)  # §3: round to the dong, half a dong rounds up


def cancel_rate(shop, p):
    O = orders_in(shop, p, valid_only=False)
    if not len(O):
        raise Unanswerable("không có đơn")
    return round(100 * (O["status"] == "huy").sum() / len(O), 2)


def cancel_count(shop, p):
    return int((orders_in(shop, p, valid_only=False)["status"] == "huy").sum())


def pct_change(cur, prev):
    if prev == 0:
        raise Unanswerable("kỳ trước bằng 0")
    return round(100 * (cur - prev) / prev, 2)


SERVICE_FEE = "phiphucvu"  # §3: the service-fee line is not a product


def lines_in(shop, p):
    """Line rows of the revenue orders in the period."""
    O = orders_in(shop, p)
    L = shop.t.get("lines")
    if L is None:
        raise Unanswerable("shop không có chi tiết mặt hàng")
    return L[L["order_id"].isin(set(O["order_id"]))]


def product_revenue(shop, p, pkey):
    L = lines_in(shop, p)
    return int(round(L.loc[L["pkey"] == pkey, "amount"].sum()))


def product_qty(shop, p, pkey):
    """Quantity converted to base units (§3)."""
    L = lines_in(shop, p)
    v = L.loc[L["pkey"] == pkey, "qty_base"].sum()
    return int(v) if float(v).is_integer() else round(float(v), 2)


def orders_with_revenue_at_least(shop, p, x):
    return int((orders_in(shop, p)["revenue_lines"] >= x).sum())


def days_with_revenue_at_least(shop, p, x):
    s = orders_in(shop, p).groupby("order_date")["revenue_lines"].sum()
    return int((s >= x).sum())


def best_day(shop, p):
    """Day with the highest revenue in the period."""
    O = orders_in(shop, p)
    s = O.groupby("order_date")["revenue_lines"].sum()
    if not len(s):
        raise Unanswerable("không có đơn")
    return s.sort_index().idxmax().isoformat()


# ---------------- rankings (§3) ----------------
import re as _re

from . import parse as _P


def _pid(L):
    if "product_id" in L:
        return L["product_id"].where(L["product_id"].notna(), L["pkey"])
    return L["pkey"]


def product_name(shop, pid):
    """Display name: the catalog name, otherwise the most frequent name on sales lines."""
    from .entity import products
    for k, (i, nm) in products(shop).items():
        if i == pid or k == pid:
            return nm
    return pid


def _rank(series, k, ascending=False):
    """Sort by value descending, ties by code ascending (§9)."""
    if not len(series):
        raise Unanswerable("không có đối tượng để xếp hạng")
    df = series.rename("v").reset_index()
    df.columns = ["id", "v"]
    df = df.sort_values(["v", "id"], ascending=[ascending, True])
    return df.head(k) if k else df


def product_sales(shop, p, by="qty"):
    L = lines_in(shop, p)
    L = L[L["pkey"] != SERVICE_FEE]
    col = {"qty": "qty_base", "revenue": "amount"}[by]
    if by == "profit":
        raise Unanswerable("chưa hỗ trợ")
    return L.groupby(_pid(L))[col].sum()


def top_products(shop, p, k, by="qty"):
    r = _rank(product_sales(shop, p, by), k)
    return [product_name(shop, i) for i in r["id"]]


def customer_display(shop, cust):
    C = shop.t.get("customers")
    if C is not None and "customer_id" in C and "name" in C:
        m = dict(zip(C["customer_id"], C["name"]))
        if cust in m:
            return m[cust]
    O = shop.t["orders"]
    names = O.loc[O["cust"] == cust, "customer_name"] if "customer_name" in O else []
    return names.value_counts().index[0] if len(names) else cust


def _cust_groups(shop):
    C = shop.t.get("customers")
    if C is None or "cust_group" not in C:
        raise Unanswerable("không có nhóm khách")
    return dict(zip(C["customer_id"], C["cust_group"].map(_P.key)))


def order_cust_group(shop, O):
    """Customer group of each order: from the customers table, otherwise from the customer-group column on the order row."""
    C = shop.t.get("customers")
    if C is not None and "cust_group" in C and "customer_id" in O:
        return O["customer_id"].map(_cust_groups(shop))
    L = shop.t.get("lines")
    if L is not None and "cust_group" in L and L["cust_group"].notna().any():
        g = L.dropna(subset=["cust_group"]).drop_duplicates("order_id").set_index("order_id")["cust_group"].map(_P.key)
        return O["order_id"].map(g)
    raise Unanswerable("không có nhóm khách")


def _has_customers(shop):
    O = shop.t["orders"]
    if not (("customer_id" in O and O["customer_id"].notna().any()) or ("customer_name" in O and O["customer_name"].notna().any())):
        raise Unanswerable("shop không ghi khách")


def customer_stats(shop, p, by="revenue"):
    """by: revenue | orders | days (days with purchases) | aov (average per order, customers with ≥3 orders) | cancels (cancelled orders)."""
    _has_customers(shop)
    O = orders_in(shop, p, valid_only=by != "cancels")
    O = O[O["cust"].notna()]
    if by == "revenue":
        return O.groupby("cust")["revenue_lines"].sum()
    if by == "days":
        return O.groupby("cust")["order_date"].nunique()
    if by == "aov":
        g = O.groupby("cust")["revenue_lines"]
        n = g.size()
        return (g.sum() / n)[n >= 3]
    if by == "cancels":
        return O[O["status"] == "huy"].groupby("cust").size()
    return O.groupby("cust").size()


def busiest_day(shop, p):
    """Busiest day: most orders."""
    s = orders_in(shop, p).groupby("order_date").size()
    if not len(s):
        raise Unanswerable("không có đơn")
    return _rank(s, 1)["id"].iloc[0].isoformat()


def peak_hour(shop, p):
    O = orders_in(shop, p)
    if "order_ts" not in O or O["order_ts"].isna().all():
        raise Unanswerable("shop không ghi giờ")
    h = O["order_ts"].dropna().map(lambda t: t.hour)
    return int(_rank(h.value_counts(), 1)["id"].iloc[0])


def most_ordered_product(shop, p):
    """Most popular product: present in the most orders."""
    L = lines_in(shop, p)
    L = L[L["pkey"] != SERVICE_FEE]
    return product_name(shop, _rank(L.groupby(_pid(L))["order_id"].nunique(), 1)["id"].iloc[0])


def top_customers(shop, p, k, by="revenue"):
    r = _rank(customer_stats(shop, p, by), k)
    return [customer_display(shop, c) for c in r["id"]]


def buyers_count(shop, p):
    return int(orders_in(shop, p)["cust"].nunique())


def buyers_with_min_orders(shop, p, n):
    s = customer_stats(shop, p, "orders")
    return int((s >= n).sum())


def pct_buyers_with_min_orders(shop, p, n):
    s = customer_stats(shop, p, "orders")
    if not len(s):
        raise Unanswerable("không có khách")
    return round(100 * (s >= n).sum() / len(s), 2)


# ---------------- by order attribute ----------------
PAY = {"cash": r"tien mat|cash|\btm\b", "transfer": r"chuyen khoan|transfer|\bck\b|bank", "ewallet": r"vi dien tu|ewallet|vi\b|momo",
       "cod": r"cod|thu ho", "debt": r"ghi no|debt|no\b"}
CHANNEL = {"store": r"store|tai quay|tai cua hang|tai tiem", "phone": r"phone|dien thoai", "zalo_oa": r"zalo", "ecom": r"\bsan\b|tmdt|shopee|lazada|tiki"}


def _norm_attr(v, table):
    k = _P.key(v)
    for name, pat in table.items():
        if _re.search(pat.replace(" ", ""), k) or _re.search(pat, str(v).lower()):
            return name
    return k


def revenue_by(shop, p, attr, value):
    """attr: pay_method | channel | cust_group | staff_id."""
    O = orders_in(shop, p)
    if attr == "cust_group":
        col = order_cust_group(shop, O)
        return int(round(O.loc[col == _P.key(value), "revenue_lines"].sum()))
    if attr not in O or O[attr].isna().all():
        raise Unanswerable(f"shop không ghi {attr}")
    table = {"pay_method": PAY, "channel": CHANNEL}.get(attr)
    col = O[attr].map(lambda v: _norm_attr(v, table)) if table else O[attr].map(_P.key)
    return int(round(O.loc[col == (value if table else _P.key(value)), "revenue_lines"].sum()))


def share(part, total):
    if not total:
        raise Unanswerable("tổng bằng 0")
    return round(100 * part / total, 2)


def shift_of(ts):
    if ts is None or ts != ts:
        return None
    h = ts.hour
    return "sang" if 6 <= h < 14 else "chieu" if 14 <= h < 22 else None


def _orders_ts(O):
    if "order_ts" not in O or O["order_ts"].isna().all():
        raise Unanswerable("shop không ghi giờ tạo đơn")
    return O["order_ts"]


def shift_revenue(shop, p, shift):
    O = orders_in(shop, p)
    return int(round(O.loc[_orders_ts(O).map(shift_of) == shift, "revenue_lines"].sum()))


def shift_orders(shop, p, shift):
    O = orders_in(shop, p)
    return int((_orders_ts(O).map(shift_of) == shift).sum())


def staff_revenue(shop, p):
    O = orders_in(shop, p)
    if "staff_id" not in O:
        raise Unanswerable("shop không ghi nhân viên")
    return O.groupby("staff_id")["revenue_lines"].sum()


def size_qty(shop, p, size):
    L = lines_in(shop, p)
    m = L["product_name"].map(lambda n: isinstance(n, str) and n.strip().lower().endswith(f"({size.lower()})"))
    return int(L.loc[m, "qty_base"].sum())


def _group_tables(shop):
    """Tables that have a product-group column: products first, then stock."""
    return [T for T in (shop.t.get("products"), shop.t.get("stock")) if T is not None and "group" in T and T["group"].notna().any()]


def line_groups(shop, L):
    """Product group (normalized) of each order line."""
    if "group" in L and L["group"].notna().any():
        return L["group"].map(lambda g: _P.key(g) if isinstance(g, str) else None)
    for T in _group_tables(shop):
        if "product_id" in T and "product_id" in L and L["product_id"].notna().any():
            return L["product_id"].map(dict(zip(T["product_id"], T["group"].map(_P.key))))
        if "pkey" in T or "product_name" in T:
            keys = T["pkey"] if "pkey" in T else T["product_name"].map(_P.key)
            return L["pkey"].map(dict(zip(keys, T["group"].map(_P.key))))
    raise Unanswerable("không có nhóm hàng")


def _group_lines(shop, p, group):
    L = lines_in(shop, p)
    return L[(line_groups(shop, L) == _P.key(group)).values]


def group_revenue(shop, p, group):
    return int(round(_group_lines(shop, p, group)["amount"].sum()))


def group_top_product(shop, p, group, by="qty"):
    L = _group_lines(shop, p, group)
    L = L[L["pkey"] != SERVICE_FEE]
    r = _rank(L.groupby(_pid(L))[{"qty": "qty_base", "revenue": "amount"}[by]].sum(), 1)
    return product_name(shop, r["id"].iloc[0])


def group_order_count(shop, p, group):
    return int(_group_lines(shop, p, group)["order_id"].nunique())


def group_qty(shop, p, group):
    v = _group_lines(shop, p, group)["qty_base"].sum()
    return int(v) if float(v).is_integer() else round(float(v), 2)


def groups(shop):
    L = shop.t.get("lines")
    if L is not None and "group" in L and L["group"].notna().any():
        return sorted(set(L["group"].dropna()))
    T = _group_tables(shop)
    return sorted(set(T[0]["group"].dropna())) if T else []


def _drugs(shop):
    D = shop.t.get("drugs")
    if D is None:
        raise Unanswerable("không có danh mục thuốc")
    return D


def rx_revenue(shop, p, rx=True):
    D = _drugs(shop)
    L = lines_in(shop, p)
    rxset = set(D.loc[D["is_rx"] == True, "product_id"])  # noqa: E712
    m = L["product_id"].isin(rxset)
    return int(round(L.loc[m if rx else ~m, "amount"].sum()))


def ingredient_revenue(shop, p, ingredient):
    D = _drugs(shop)
    L = lines_in(shop, p)
    ids = set(D.loc[D["ingredient"].map(lambda v: isinstance(v, str) and v.strip().lower() == ingredient.strip().lower()), "product_id"])
    return int(round(L.loc[L["product_id"].isin(ids), "amount"].sum()))


def ingredients(shop):
    D = shop.t.get("drugs")
    return sorted(set(D["ingredient"].dropna())) if D is not None else []


# ---------------- purchases (§5) ----------------
def _receipts(shop):
    """→ DataFrame per receipt: receipt_id, receipt_date, total, cancelled."""
    import pandas as pd
    Pu, PL = shop.t.get("purchases"), shop.t.get("purchase_lines")
    if Pu is None and PL is None:
        raise Unanswerable("shop không có dữ liệu nhập hàng")
    if PL is not None:
        amt = PL["in_amount"] if "in_amount" in PL else PL["in_qty"] * PL["in_price"]
        byr = PL.assign(_a=amt).groupby("receipt_id").agg(_a=("_a", "sum"), **({"receipt_date": ("receipt_date", "first")} if "receipt_date" in PL else {}))
    else:
        byr = pd.DataFrame()
    if Pu is not None:
        R = Pu.drop_duplicates("receipt_id").set_index("receipt_id")
        if "receipt_total" not in R:
            R["receipt_total"] = byr["_a"] if len(byr) else None
        out = R
    else:
        out = byr.rename(columns={"_a": "receipt_total"})
    out = out.reset_index()
    st = out["receipt_status"] if "receipt_status" in out else pd.Series("", index=out.index)
    out["cancelled"] = st.map(lambda v: isinstance(v, str) and bool(_re.search(r"hủy|huỷ|cancel", v.lower())))
    return out


def purchase_total(shop, p):
    R = _receipts(shop)
    m = R["receipt_date"].map(lambda d: d is not None and p.start <= d <= p.end) & ~R["cancelled"]
    return int(round(R.loc[m, "receipt_total"].sum()))


def avg_import_price(shop, p, pkey, unit=None):
    """Average weighted by purchased quantity, in the purchase unit, receipts dated in the period, cancelled receipts excluded."""
    PL = shop.t.get("purchase_lines")
    if PL is None or "in_price" not in PL:
        raise Unanswerable("không có giá nhập")
    R = _receipts(shop).set_index("receipt_id")
    PL = PL.copy()
    if "receipt_date" not in PL:
        PL["receipt_date"] = PL["receipt_id"].map(R["receipt_date"])
    PL["cancel"] = PL["receipt_id"].map(R["cancelled"]).fillna(False)
    if "product_name" in PL:
        PL["pk"] = PL["product_name"].map(_P.key)
    else:
        from .entity import products
        id2k = {i: k for k, (i, _) in products(shop).items() if i}
        PL["pk"] = PL["product_id"].map(id2k)
    m = (PL["pk"] == pkey) & ~PL["cancel"] & PL["receipt_date"].map(lambda d: d is not None and p.start <= d <= p.end)
    if unit and "in_unit" in PL:
        mu = m & (PL["in_unit"].map(_P.key) == _P.key(unit))
        m = mu if mu.any() else m
    X = PL[m]
    if not len(X) or X["in_qty"].sum() == 0:
        raise Unanswerable("không có phiếu nhập trong kỳ")
    v = (X["in_qty"] * X["in_price"]).sum() / X["in_qty"].sum()
    return int(v + 0.5)


# ---------------- receivables (§4) ----------------
def _pay_kind(v):
    return _norm_attr(v, PAY) if v is not None and v == v else None


def _debt_base(shop):
    O, Pm = shop.t["orders"], shop.t.get("payments")
    if Pm is None or "total_due" not in O:
        raise Unanswerable("shop không có dữ liệu thanh toán để tính nợ")
    O = O[O["status"] != "huy"].copy()
    if "pay_method" in O:
        O = O[O["pay_method"].map(_pay_kind) != "cod"]  # COD and e-commerce marketplaces are not customer debt
    O["pk"] = O["pay_method"].map(_pay_kind) if "pay_method" in O else None
    Pm = Pm.copy()
    Pm["pay_date"] = Pm["pay_ts"].map(lambda t: t.date() if t is not None and t == t else None)
    return O, Pm


_AMT = r"(\d[\d.,]*)\s*(k|nghin|ngan|tr|trieu|d|dong|đ)?\b"


def _amt(m):
    v = float(m[1].replace(".", "").replace(",", "."))
    return v * {"k": 1e3, "nghin": 1e3, "ngan": 1e3, "tr": 1e6, "trieu": 1e6}.get(m[2] or "", 1)


def note_remaining(note, due):
    """Amount still owed read from the note of a debt order ('còn thiếu 73 nghìn', 'đưa trước 236k, còn lại ghi sổ', 'nợ cả đơn'); None if unreadable."""
    from .period import norm
    s = norm(str(note))
    if _re.search(r"\bdu\b|het roi|tra het", s):
        return 0.0
    if (m := _re.search(r"(?:thieu(?: lai)?|\bno|ghi so) " + _AMT, s)):
        return _amt(m)
    if _re.search(r"con lai", s) and (m := _re.search(r"(?:dua truoc|\btra|\bck|dua) " + _AMT, s)):
        return due - _amt(m)
    if _re.search(r"ca don|chua tra", s):
        return float(due)
    return None


def _note_debt_orders(shop, x):
    """Shop without a payment book: the note on a debt order is the state at the end of the data → only usable when x ≥ last data date."""
    O = shop.t["orders"]
    if not {"note", "total_due", "pay_method"} <= set(O) or shop.data_end is None or x < shop.data_end:
        raise Unanswerable("shop không có dữ liệu thanh toán để tính nợ")
    O = O[(O["status"] != "huy") & (O["pay_method"].map(_pay_kind) == "debt")].copy()
    O["remaining"] = [note_remaining(n, d) for n, d in zip(O["note"], O["total_due"])]
    if O["remaining"].isna().any():
        raise Unanswerable("ghi chú nợ không đọc được")
    O = O[O["remaining"] > 0.5]
    O["age"] = O["order_date"].map(lambda d: (x - d).days)
    return O


def debt_orders(shop, x):
    """Orders still owing at end of day x: columns remaining, age (days since the order date)."""
    if x < shop.data_start:
        raise Unanswerable("trước khi có dữ liệu")
    if shop.t.get("payments") is None:
        return _note_debt_orders(shop, x)
    O, Pm = _debt_base(shop)
    O = O[O["order_date"].map(lambda d: d is not None and d <= x)]
    paid = Pm[Pm["pay_date"].map(lambda d: d is not None and d <= x)].groupby("order_id")["pay_amount"].sum()
    O["remaining"] = O["total_due"] - O["order_id"].map(paid).fillna(0)
    O = O[O["remaining"] > 0.5]
    O["age"] = O["order_date"].map(lambda d: (x - d).days)
    return O


def total_debt(shop, x):
    return int(round(debt_orders(shop, x)["remaining"].sum()))


def debtors_count(shop, x):
    return int(debt_orders(shop, x)["cust"].nunique())


def top_debtors(shop, x, k):
    O = debt_orders(shop, x)
    r = _rank(O[O["cust"].notna()].groupby("cust")["remaining"].sum(), k)
    return {"columns": ["khach_hang", "so_tien_no"],
            "rows": [[customer_display(shop, c), int(round(v))] for c, v in zip(r["id"], r["v"])]}


def debt_aging(shop, x, buckets):
    """buckets: [(lo, hi), ...] by debt age, hi=None means unbounded."""
    O = debt_orders(shop, x)
    return [int(round(O.loc[(O["age"] >= lo) & ((O["age"] <= hi) if hi is not None else True), "remaining"].sum())) for lo, hi in buckets]


def overdue_debt(shop, x, n):
    O = debt_orders(shop, x)
    return int(round(O.loc[O["age"] > n, "remaining"].sum()))


def _credit_orders(shop):
    O, Pm = _debt_base(shop)
    return O[O["pk"] == "debt"], Pm


def new_debt(shop, p, cust=None):
    """New debt: the part of the order total not paid on the purchase day, for debt orders placed in the period."""
    _check_range(shop, p)
    O, Pm = _credit_orders(shop)
    O = O[O["order_date"].map(lambda d: d is not None and p.start <= d <= p.end)]
    if cust is not None:
        O = O[O["cust"] == cust]
    od = dict(zip(O["order_id"], O["order_date"]))
    same = Pm[Pm["order_id"].isin(od) & (Pm["order_id"].map(od) == Pm["pay_date"])].groupby("order_id")["pay_amount"].sum()
    return int(round((O["total_due"] - O["order_id"].map(same).fillna(0)).clip(lower=0).sum()))


def debt_collected(shop, p, cust=None):
    """Debt collected: payments after the purchase day, dated in the period, for every debt order (including earlier orders and returned orders)."""
    _check_range(shop, p)
    O, Pm = _credit_orders(shop)
    if cust is not None:
        O = O[O["cust"] == cust]
    od = dict(zip(O["order_id"], O["order_date"]))
    X = Pm[Pm["order_id"].isin(od)]
    X = X[X["pay_date"].map(lambda d: d is not None and p.start <= d <= p.end) & (X["pay_date"] > X["order_id"].map(od))]
    return int(round(X["pay_amount"].sum()))


def find_customer(shop, question):
    """Customer named in the question (accent-free key, phone number removed). → cust or None."""
    from .parse import key, strip_phone
    q = key(question)
    O = shop.t["orders"]
    cands = {}
    C = shop.t.get("customers")
    if C is not None and "customer_id" in C and "name" in C:
        for i, n in zip(C["customer_id"], C["name"]):
            cands[key(strip_phone(n))] = i
    if "customer_name" in O:
        for c, n in zip(O["cust"], O["customer_name"]):
            if c is not None and c == c:
                cands.setdefault(key(strip_phone(n)), c)
    best = None
    for k, c in cands.items():
        if len(k) >= 6 and k in q and (best is None or len(k) > len(best[0])):
            best = (k, c)
    return best[1] if best else None


# ---------------- selling price, price-increase effect (§5) ----------------
def _factor(shop, pkey, unit):
    conv = shop.t["conv"]
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    u = _P.key(unit)
    for r in conv.itertuples():
        if _P.key(r.unit) == u and (r.pkey == pkey or (pid and r.product_id == pid)):
            return r.factor
    return 1


def price_on(shop, d, pkey):
    """Unit price per base unit, before line discount, on orders placed on day d (including cancelled and returned)."""
    L = shop.t.get("lines")
    if L is None:
        raise Unanswerable("không có dòng hàng")
    X = L[(L["pkey"] == pkey) & L["order_date"].map(lambda x: x == d)] if "order_date" in L else None
    if X is None or not len(X):
        O = shop.t["orders"]
        ids = set(O.loc[O["order_date"] == d, "order_id"])
        X = L[(L["pkey"] == pkey) & L["order_id"].isin(ids)]
    if not len(X):
        raise Unanswerable("ngày đó không bán mặt hàng này")
    if "unit_price" in X and X["unit_price"].notna().any():
        per = [up / (_factor(shop, pkey, u) if u else 1) for up, u in zip(X["unit_price"], X.get("unit", [None] * len(X))) if up == up]
    else:
        per = [(a + (dc if dc == dc else 0)) / qb for a, dc, qb in zip(X["amount"], X.get("discount", [0] * len(X)), X["qty_base"]) if qb]
    v = max(set(per), key=per.count)
    return int(v) if float(v).is_integer() else round(v, 2)


def qty_between(shop, pkey, start, end):
    from .period import Period
    return product_qty(shop, Period(start, end), pkey)


def price_effect(shop, pkey, d, n):
    """% change in quantity (base units) over N days from d (including d) versus the N days right before d."""
    import datetime as dt
    after = qty_between(shop, pkey, d, d + dt.timedelta(days=n - 1))
    before = qty_between(shop, pkey, d - dt.timedelta(days=n), d - dt.timedelta(days=1))
    return pct_change(after, before)


def price_increase_date(shop, pkey, new_price=None):
    """Price increase (from the price table) to new_price; if several, take the first."""
    Pr = shop.t.get("prices")
    if Pr is None:
        raise Unanswerable("không có bảng giá")
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    m = (Pr["product_name"].map(_P.key) == pkey) if "product_name" in Pr else (Pr["product_id"] == pid)
    X = Pr[m].sort_values("price_date")
    prev = None
    for r in X.itertuples():
        if prev is not None and r.new_price > prev and (new_price is None or abs(r.new_price - new_price) < 1):
            return r.price_date
        prev = r.new_price
    raise Unanswerable("không thấy lần tăng giá")


# ---------------- per product in a period ----------------
def unsold_count(shop, p):
    """Products sold before the period but with no order in the period (§5)."""
    from .period import Period
    import datetime as dt
    O = shop.t["orders"]
    L = shop.t["lines"]
    valid = O[O["status"].isin(VALID)]
    before_ids = set(valid.loc[valid["order_date"].map(lambda d: d is not None and d < p.start), "order_id"])
    _check_range(shop, p)
    in_ids = set(valid.loc[valid["order_date"].map(lambda d: d is not None and p.start <= d <= p.end), "order_id"])
    pid = _pid(L)
    sold_before = set(pid[L["order_id"].isin(before_ids)]) - {SERVICE_FEE}
    sold_in = set(pid[L["order_id"].isin(in_ids)])
    return len(sold_before - sold_in)


def products_in_min_orders(shop, p, n):
    L = lines_in(shop, p)
    L = L[L["pkey"] != SERVICE_FEE]
    return int((L.groupby(_pid(L))["order_id"].nunique() >= n).sum())


# ---------------- multiple months ----------------
def monthly_revenue(shop, months):
    from .period import month
    return [revenue(shop, month(y, m)) for y, m in months]


def best_month(shop, months):
    v = monthly_revenue(shop, months)
    y, m = months[max(range(len(v)), key=lambda i: v[i])]
    return f"{y:04d}-{m:02d}"


def increasing(shop, months):
    v = monthly_revenue(shop, months)
    return all(b > a for a, b in zip(v, v[1:]))


# ---------------- stock, lots (§5) ----------------
def stock_at(shop, x, pkey):
    """Stock (base units) at end of day x. With a stock card, look it up; otherwise only answer at the last data date."""
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    M = shop.t.get("stock_moves")
    if M is not None:
        X = M[(M["product_id"] == pid) & M["move_ts"].map(lambda t: t is not None and t.date() <= x)]
        if not len(X):
            return 0
        return int(X.sort_values("move_ts")["stock_after"].iloc[-1])
    S = shop.t.get("stock")
    if S is None and shop.t.get("lots") is not None and shop.t.get("line_lots") is not None:
        Lo = lot_remaining(shop, x)  # pharmacy without a stock table: sum the stock of its lots
        return int(Lo.loc[Lo["product_id"] == pid, "remaining"].sum())
    if S is None:
        raise Unanswerable("shop không có dữ liệu tồn kho")
    if x != shop.data_end:
        raise Unanswerable("chỉ có tồn tại ngày cuối dữ liệu")  # shortcut: stock is not rolled back by movements yet; needed when a question asks about another date
    m = (S["product_id"] == pid) if "product_id" in S and pid else (S["product_name"].map(_P.key) == pkey)
    if not m.any():
        raise Unanswerable("không thấy mặt hàng trong bảng tồn")
    return int(S.loc[m, "stock_qty"].iloc[0])


def big_units(shop, pkey):
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    c = shop.t["conv"]
    return list(c.loc[(c["pkey"] == pkey) | ((c["product_id"] == pid) & c["product_id"].notna()), "unit"])


def stock_split(shop, x, pkey, big_unit):
    q = stock_at(shop, x, pkey)
    f = _factor(shop, pkey, big_unit)
    if f == 1:
        raise Unanswerable("không có hệ số quy đổi")
    return [int(q // f), int(q % f)]


def stock_value(shop, x):
    S = shop.t.get("stock")
    P = shop.t.get("products")
    M = shop.t.get("stock_moves")
    if M is not None and P is not None and "cost" in P:
        X = M[M["move_ts"].map(lambda t: t is not None and t.date() <= x)].sort_values("move_ts")
        last = X.groupby("product_id")["stock_after"].last()
        cost = dict(zip(P["product_id"], P["cost"]))
        return int(round(sum(max(q, 0) * cost.get(i, 0) for i, q in last.items())))
    if S is None or P is None or "cost" not in P:
        raise Unanswerable("thiếu tồn kho hoặc giá vốn")
    if x != shop.data_end:
        raise Unanswerable("chỉ có tồn tại ngày cuối dữ liệu")
    cost = dict(zip(P["product_id"], P["cost"])) if "product_id" in S and "product_id" in P else dict(zip(P["pkey"], P["cost"]))
    k = S["product_id"] if "product_id" in S and "product_id" in P else S["product_name"].map(_P.key)
    v = (S["stock_qty"].clip(lower=0) * k.map(cost)).sum()
    return int(round(v))


def lot_remaining(shop, x):
    """Stock of each lot (base units) at end of day x."""
    Lo, LL = shop.t.get("lots"), shop.t.get("line_lots")
    if Lo is None or LL is None:
        raise Unanswerable("shop không có dữ liệu lô")
    O = shop.t["orders"]
    ok = set(O.loc[O["order_date"].map(lambda d: d is not None and d <= x) & (O["status"] != "huy"), "order_id"])
    X = LL[LL["order_id"].isin(ok)]
    used = X.groupby("lot")["lot_qty_base"].sum() - X.groupby("lot")["lot_return_base"].sum().fillna(0) if "lot_return_base" in X else X.groupby("lot")["lot_qty_base"].sum()
    Lo = Lo.copy()
    rec = None
    if "receipt_id" in Lo:
        try:
            R = _receipts(shop).set_index("receipt_id")["receipt_date"]
            rec = Lo["receipt_id"].map(R)
        except Unanswerable:
            pass
    if rec is not None:
        Lo = Lo[rec.map(lambda d: d is None or d != d or d <= x)]
    Lo["remaining"] = Lo["in_qty_base"] - Lo["lot"].map(used).fillna(0)
    return Lo


def nearest_expiry(shop, x, pkey):
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    Lo = lot_remaining(shop, x)
    X = Lo[(Lo["product_id"] == pid) & (Lo["remaining"] > 0) & Lo["expiry"].map(lambda e: e is not None and e >= x)]
    if not len(X):
        raise Unanswerable("không còn lô")
    return min(X["expiry"]).isoformat()


def lots_left(shop, x, pkey):
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    Lo = lot_remaining(shop, x)
    return int(((Lo["product_id"] == pid) & (Lo["remaining"] > 0)).sum())


# ---------------- deliveries, suppliers ----------------
def credit_due_count(shop, x, due=None):
    """Credit sales (building materials): number of non-cancelled orders placed up to end of day x whose due date falls in period due; due None → due after day x."""
    C = shop.t["credit"].merge(shop.t["orders"][["order_id", "order_date", "status"]], on="order_id")
    C = C[(C["status"] != "huy") & C["order_date"].map(lambda d: d is not None and d <= x)]
    if due is None:
        return int((C["due_date"] > x).sum())
    return int(C["due_date"].map(lambda d: due.start <= d <= due.end).sum())


def _delivered(shop, p, x):
    """Delivery runs (up to end of day x) of orders placed in period p."""
    D = shop.t["deliveries"].merge(shop.t["orders"][["order_id", "order_date"]], on="order_id")
    return D[D["order_date"].map(lambda d: p.start <= d <= p.end) & D["delivery_date"].map(lambda d: d is not None and d <= x)]


def orders_min_deliveries(shop, p, x, n):
    """Number of orders placed in period p delivered in n runs or more up to end of day x."""
    return int((_delivered(shop, p, x).groupby("order_id")["delivery_no"].nunique() >= n).sum())


def delivered_qty(shop, p, x, pkey):
    """Quantity (base units) of a product delivered up to end of day x for orders placed in period p."""
    D = _delivered(shop, p, x)
    v = D.loc[D["product_name"].map(_P.key) == pkey, "qty_base"].sum()
    return int(v) if float(v).is_integer() else round(float(v), 2)


def delivery_count(shop, p):
    D = shop.t.get("deliveries")
    if D is None:
        raise Unanswerable("shop không có sổ giao hàng")
    _check_range(shop, p)
    X = D[D["delivery_date"].map(lambda d: d is not None and p.start <= d <= p.end)]
    return int(X[["order_id", "delivery_no"]].drop_duplicates().shape[0])


def top_supplier(shop, p, by="amount"):
    R = _receipts(shop)
    m = R["receipt_date"].map(lambda d: d is not None and p.start <= d <= p.end) & ~R["cancelled"]
    col = "supplier" if "supplier" in R else "supplier_id"
    if col not in R:
        PL = shop.t.get("purchase_lines")
        if PL is not None and "supplier" in PL:
            R = R.merge(PL.groupby("receipt_id")["supplier"].first().reset_index(), on="receipt_id", how="left")
            col = "supplier"
        else:
            raise Unanswerable("không có nhà cung cấp")
    s = R[m].groupby(col)["receipt_total"].sum() if by == "amount" else R[m].groupby(col)["receipt_id"].nunique()
    sid = _rank(s, 1)["id"].iloc[0]
    Su = shop.t.get("suppliers")
    if Su is not None and col == "supplier_id":
        return dict(zip(Su["supplier_id"], Su["name"])).get(sid, sid)
    return sid


# ---------------- profit (§5) ----------------
def _line_cost(L):
    if "cost" not in L or L["cost"].isna().all():
        raise Unanswerable("shop không ghi giá vốn trên dòng bán")
    return L["qty"].fillna(0) * L["cost"].fillna(0)


def gross_profit(shop, p):
    L = lines_in(shop, p)
    return int(round(L["amount"].sum() - _line_cost(L).sum()))


def top_products_by_profit(shop, p, k=1):
    L = lines_in(shop, p)
    L = L[L["pkey"] != SERVICE_FEE]
    prof = (L["amount"] - _line_cost(L)).groupby(_pid(L)).sum()
    return [product_name(shop, i) for i in _rank(prof, k)["id"]]


def net_profit(shop, p):
    E = shop.t.get("expenses")
    if E is None:
        raise Unanswerable("shop không có sổ chi phí")
    exp = E.loc[E["expense_date"].map(lambda d: d is not None and p.start <= d <= p.end), "expense_amount"].sum()
    return int(round(gross_profit(shop, p) - exp))


# ---------------- quantities in base units (§3) ----------------
def base_unit_of_lines(shop, L):
    """Base unit of each line: from the conversion table if the line is sold in a big unit, otherwise the line's own unit."""
    conv = shop.t["conv"]
    big = {(r.pkey, _P.key(r.unit)): r.base_unit for r in conv.itertuples() if r.pkey}
    bigid = {(r.product_id, _P.key(r.unit)): r.base_unit for r in conv.itertuples() if r.product_id}
    P = shop.t.get("products")
    pb = dict(zip(P["pkey"], P["base_unit"])) if P is not None and "base_unit" in P else {}
    S = shop.t.get("stock")  # the catalog lives in the stock file
    sb = {}
    if S is not None and "base_unit" in S:
        if "product_name" in S:
            sb.update(zip(S["product_name"].map(_P.key), S["base_unit"]))
        if "product_id" in S:
            sb.update(zip(S["product_id"], S["base_unit"]))
    out = []
    for pk, pid, u in zip(L["pkey"], L["product_id"] if "product_id" in L else [None] * len(L), L["unit"] if "unit" in L else [None] * len(L)):
        ku = _P.key(u)
        b = big.get((pk, ku)) or bigid.get((pid, ku)) or pb.get(pk) or sb.get(pid) or sb.get(pk) or u
        out.append(_P.key(b))
    return out


def qty_by_base_unit(shop, p, unit):
    L = lines_in(shop, p)
    L = L[L["pkey"] != SERVICE_FEE]
    m = [b == _P.key(unit) for b in base_unit_of_lines(shop, L)]
    v = L.loc[m, "qty_base"].sum()
    return int(v) if float(v).is_integer() else round(float(v), 2)


# ---------------- lots close to expiry (pharmacy) ----------------
def expiring_lots(shop, x, start, end):
    Lo = lot_remaining(shop, x)
    return Lo[(Lo["remaining"] > 0) & Lo["expiry"].map(lambda e: e is not None and start <= e <= end)]


def expiring_products(shop, x, start, end):
    X = expiring_lots(shop, x, start, end)
    first = X.groupby("product_id")["expiry"].min().reset_index().sort_values(["expiry", "product_id"])
    return [product_name(shop, i) for i in first["product_id"]]


def expiring_value(shop, x, start, end):
    """Cost of the remaining stock of a lot, at that lot's purchase price converted to the base unit."""
    X = expiring_lots(shop, x, start, end)
    if "lot_unit_cost" in X and X["lot_unit_cost"].notna().any():
        c = X["lot_unit_cost"]
    else:
        PL = shop.t.get("purchase_lines")
        if PL is None or "lot" not in PL or "in_price" not in PL:
            raise Unanswerable("không có giá nhập theo lô")
        unit = PL["in_unit"] if "in_unit" in PL else [None] * len(PL)
        pk = PL["product_name"].map(_P.key) if "product_name" in PL else PL["product_id"]
        per = {}
        from .entity import products
        id2k = {i: k for k, (i, _) in products(shop).items() if i}
        for lot, pr, u, k in zip(PL["lot"], PL["in_price"], unit, pk):
            kk = k if "product_name" in PL else id2k.get(k, k)
            per[lot] = pr / _factor(shop, kk, u) if u else pr
        c = X["lot"].map(per)
    return int(round((X["remaining"] * c).sum()))


# ---------------- purchased minus sold, out of stock ----------------
def in_minus_out(shop, p, pkey):
    """Purchased (base units) minus sold (§1 orders, base units) for one product in the period."""
    PL = shop.t.get("purchase_lines")
    Lo = shop.t.get("lots")
    from .entity import products
    pid = products(shop).get(pkey, (None, None))[0]
    R = _receipts(shop).set_index("receipt_id")
    if PL is not None and ("in_qty" in PL):
        X = PL.copy()
        if "receipt_date" not in X:
            X["receipt_date"] = X["receipt_id"].map(R["receipt_date"])
        X["cancel"] = X["receipt_id"].map(R["cancelled"]).fillna(False)
        m = (X["product_name"].map(_P.key) == pkey) if "product_name" in X else (X["product_id"] == pid)
        m &= ~X["cancel"] & X["receipt_date"].map(lambda d: d is not None and p.start <= d <= p.end)
        unit = X["in_unit"] if "in_unit" in X else [None] * len(X)
        inq = sum(q * (_factor(shop, pkey, u) if u else 1) for q, u, ok in zip(X["in_qty"], unit, m) if ok)
    elif Lo is not None:
        X = Lo.copy()
        X["receipt_date"] = X["receipt_id"].map(R["receipt_date"])
        m = (X["product_id"] == pid) & X["receipt_date"].map(lambda d: d is not None and p.start <= d <= p.end)
        inq = X.loc[m, "in_qty_base"].sum()
    else:
        raise Unanswerable("không có dữ liệu nhập")
    v = inq - product_qty(shop, p, pkey)
    return int(v) if float(v).is_integer() else round(float(v), 2)


def out_of_stock_count(shop, x):
    """Products bought for resale with stock = 0 at end of day x."""
    S = shop.t.get("stock")
    if S is None:
        Lo = lot_remaining(shop, x)
        tot = Lo.groupby("product_id")["remaining"].sum()
        return int((tot <= 0).sum())
    if x != shop.data_end:
        raise Unanswerable("chỉ có tồn tại ngày cuối dữ liệu")
    bought = set()
    PL = shop.t.get("purchase_lines")
    if PL is not None:
        bought = set(PL["product_id"]) if "product_id" in PL else set(PL["product_name"].map(_P.key))
    k = S["product_id"] if "product_id" in S and PL is not None and "product_id" in PL else S["product_name"].map(_P.key)
    m = (S["stock_qty"] <= 0) & (k.isin(bought) if bought else True)
    return int(m.sum())
