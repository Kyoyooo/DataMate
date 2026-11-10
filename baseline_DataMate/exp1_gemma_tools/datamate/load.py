"""Load one shop's data package into the common frame (docs/formats.md section 3).

Shop(path).t  →  dict canonical table name → DataFrame:
  lines, orders, products, conv, customers, payments, purchases, purchase_lines, lots, line_lots,
  stock, prices, deliveries, credit, drugs, tables, expenses, returns, stock_moves
"""
import datetime as dt
import os
import pickle
import re
import sqlite3
import warnings
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import parse as P
from .readme import parse as parse_readme, table_key
from .synonyms import lookup

warnings.filterwarnings("ignore")
CACHE = Path(os.environ.get("DATAMATE_CACHE", Path(__file__).resolve().parent.parent / ".cache"))
VERSION = 10  # bump when the loading logic changes, to invalidate old caches

ORDER_LEVEL = ["order_id", "order_date", "order_ts", "status", "customer_name", "customer_id"]
ORDER_FIELDS = ("channel", "staff_id", "pay_method", "cust_group", "total_due", "paid", "debt", "goods_total", "discount",
                "ship_fee", "area", "table_no", "guests", "address", "phone", "trade_in", "note")  # order-level information, may be written on line rows
MONEY = {"unit_price", "amount", "discount", "line_discount", "cost", "price", "goods_total", "total_due", "paid", "debt", "pay_amount",
         "receipt_total", "in_price", "in_amount", "trade_in", "new_price", "old_price", "big_price", "ship_fee", "refund",
         "expense_amount", "lot_unit_cost", "vat"}
NUMBER = {"qty_base", "lot_qty_base", "lot_return_base", "in_qty_base", "in_qty", "factor", "stock_qty", "delivery_no",
          "credit_days", "guests", "line_no", "in_line_no", "move_qty_base", "stock_after"}
DATES = {"warranty_date", "order_date", "receipt_date", "expiry", "delivery_date", "due_date", "price_date", "expense_date", "created"}
TS = {"order_ts", "pay_ts", "return_ts", "move_ts"}
STR = {"imei", "order_id", "product_id", "customer_id", "receipt_id", "payment_id", "lot", "supplier_id", "staff_id"}


# ---------- raw reading ----------
def _raw_tables(folder):
    """→ list (list name, file name, sheet name, DataFrame without header, has_header)."""
    out = []
    for f in sorted(Path(folder).iterdir()):
        if f.suffix == ".csv":
            out.append((table_key(f.name), f.name, None, pd.read_csv(f, header=None, dtype=object), False))
        elif f.suffix == ".xlsx":
            sheets = pd.read_excel(f, sheet_name=None, header=None, dtype=object)
            # many sheets without a year → each sheet is its own list; otherwise sheets are per month
            per_list = len(sheets) > 1 and not any(P.sheet_year(s) for s in sheets)
            for s, df in sheets.items():
                # a sheet without a year among monthly sheets (e.g. 'Ghi tắt') is a separate list
                own = per_list or (len(sheets) > 1 and not P.sheet_year(s))
                out.append((s if own else table_key(f.name), f.name, s, df, False))
        elif f.suffix in (".sqlite", ".db"):
            con = sqlite3.connect(f)
            for (t,) in con.execute("select name from sqlite_master where type='table'"):
                out.append((t, f.name, None, pd.read_sql(f"select * from [{t}]", con), True))
            con.close()
    return out


def _find_header(df, known):
    best, best_n = 0, -1
    for i in range(min(8, len(df))):
        n = sum(P.key(v) in known for v in df.iloc[i].tolist() if isinstance(v, str))
        if n > best_n:
            best, best_n = i, n
    return best


SUBTOTAL = re.compile(r"^\s*(t[ổo]ng|cộng)(\s+(ngày|tháng|năm|cộng|kỳ)|\s*$|\s*:)", re.I)


class Shop:
    def __init__(self, folder, data_root=None, use_cache=True):
        self.folder = Path(folder)
        self.id = self.folder.name
        self.readme = parse_readme(self.folder / "README.md")
        self.unknown_cols = []
        cp = CACHE / f"{self.id}.v{VERSION}.pkl"
        if use_cache and cp.exists() and cp.stat().st_mtime > max(p.stat().st_mtime for p in self.folder.iterdir()):
            self.t, self.unknown_cols, self.colmap = pickle.loads(cp.read_bytes())
        else:
            self.qmap, self.plain = lookup(data_root or self.folder.parent)
            self.t = self._build()
            CACHE.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(pickle.dumps((self.t, self.unknown_cols, self.colmap)))
        self.data_end = self.readme["data_end"]
        self._meta()

    # ---------- column mapping ----------
    def _roles_for(self, tname, fname, sheet):
        rt = self.readme["tables"]
        for k in (sheet, fname, tname):
            if k and k in rt:
                return {P.key(c): r for c, r in rt[k].items()}
        for k, v in rt.items():  # README says 'So_chi_tiet_ban_hang_1.xlsx', files of the same list
            if table_key(k) == tname:
                return {P.key(c): r for c, r in v.items()}
        return None

    def _role(self, readme_roles, tname, col):
        kc = P.key(col)
        if readme_roles is not None and kc in readme_roles:
            return readme_roles[kc]
        if (P.key(tname), kc) in self.qmap:
            return self.qmap[(P.key(tname), kc)]
        if readme_roles is None and kc in self.plain:
            return self.plain[kc]
        return None

    def _logical(self):
        """→ {list name: DataFrame with canonical column names + _year, _sheet columns}."""
        self.colmap = []  # (list, source column, role): for inspection / to show the LLM
        known = {kc for (_, kc) in self.qmap} | set(self.plain)
        for cols in self.readme["tables"].values():
            known |= {P.key(c) for c in cols}
        groups = defaultdict(list)
        for tname, fname, sheet, df, has_header in _raw_tables(self.folder):
            if not has_header:
                h = _find_header(df, known)
                df = df.iloc[h + 1:].set_axis([str(c) for c in df.iloc[h].tolist()], axis=1)
            df = df.loc[:, ~pd.Index(df.columns).duplicated()]  # two columns with the same name: keep the first
            roles = self._roles_for(tname, fname, sheet)
            ren = {}
            for c in df.columns:
                r = self._role(roles, tname, c)
                if r and not r.startswith("?") and r not in ren.values():
                    ren[c] = r
                    self.colmap.append((tname, str(c), r))
                elif r is None and c and c != "nan":
                    self.unknown_cols.append((tname, c))
            df = df[list(ren)].rename(columns=ren)
            df = df.dropna(how="all")
            df["_year"] = P.sheet_year(sheet)
            df["_sheet"] = sheet or fname
            groups[tname].append(df)
        return {t: pd.concat(v, ignore_index=True) for t, v in groups.items()}

    # ---------- value normalization ----------
    @staticmethod
    def _clean(df):
        df = df.copy()
        # drop total rows (TỔNG NGÀY 18/05, Tổng tháng 6/2026): the label can be in any text column
        bad = pd.Series(False, index=df.index)
        for c in df.columns:
            if c.startswith("_") or c in ("expense_cat",):
                continue
            bad |= df[c].map(lambda v: isinstance(v, str) and bool(SUBTOTAL.match(v)))
        df = df[~bad]
        prod = [c for c in ("product_name", "product_id", "vehicle") if c in df]
        if prod and ({"amount", "qty", "unit_price"} & set(df.columns)):
            df = df[df[prod].notna().any(axis=1)]  # a line row without a product = an unlabeled total row
        if "order_id" in df and prod:
            # order cells left blank on later rows of the same order → take them from the first row of the group (rulebook §8)
            grp = df["order_id"].notna().cumsum()
            for c in ORDER_LEVEL:
                if c in df:
                    df[c] = df.groupby(grp)[c].ffill()
        for c in list(df.columns):
            if c in MONEY:
                df[c] = df[c].map(P.money)
            elif c in NUMBER:
                df[c] = df[c].map(lambda v: P.qty(v)[0])
            elif c == "qty":
                q = df[c].map(P.qty)
                df[c] = q.map(lambda x: x[0])
                df["_qty_unit"] = q.map(lambda x: x[1])
            elif c in DATES or c in TS:
                d = [P.date(v, y) for v, y in zip(df[c], df["_year"])]
                if c in TS:
                    df[c] = [pd.Timestamp.combine(a, b) if a and b else (pd.Timestamp(a) if a else None) for a, b in d]
                else:
                    df[c] = [a for a, _ in d]
                    if c == "order_date" and any(b for _, b in d):
                        df["_order_ts2"] = [pd.Timestamp.combine(a, b) if a and b else None for a, b in d]
            elif c == "status":
                df["status_raw"] = df[c]
                df[c] = df[c].map(P.status)
            elif c in STR:
                df[c] = df[c].map(lambda v: None if P.is_blank(v) else str(v).strip().removesuffix(".0"))
            elif c == "is_rx":
                df[c] = df[c].map(lambda v: str(v).strip().lower() in ("true", "1", "1.0", "x", "có"))
        return df.drop(columns=["_year"], errors="ignore")

    # ---------- table classification ----------
    @staticmethod
    def _kind(cols):
        c = set(cols)
        has = lambda *xs: all(x in c for x in xs)
        anyof = lambda *xs: any(x in c for x in xs)
        if has("expense_amount"): return "expenses"
        if has("commission"): return "staff"
        if has("warranty_date"): return "warranties"
        if has("trade_in", "order_id") and not anyof("product_name", "product_id"): return "trade_ins"
        if has("vehicle", "amount"): return "lines"  # motorbike repair ledger: one row per ticket
        if has("return_id"): return "returns"
        if has("move_qty_base") or has("stock_after"): return "stock_moves"
        if has("delivery_no") or has("delivery_date"): return "deliveries"
        if anyof("credit_days", "due_date"): return "credit"
        if anyof("table_no", "guests") and not anyof("product_name", "product_id"): return "tables"  # restaurant line rows also have a Table column
        if has("price_date"): return "prices"
        if anyof("ingredient", "is_rx") and not anyof("order_id"): return "drugs"
        if has("factor"): return "conv"
        if has("stock_qty"): return "stock"
        if has("order_id", "lot"): return "line_lots"
        if has("lot") and not anyof("in_price", "in_amount") and has("in_qty_base"): return "lots"
        if anyof("receipt_id", "receipt_date") and anyof("product_id", "product_name"): return "purchase_lines"
        if anyof("receipt_id"): return "purchases"
        if anyof("payment_id", "pay_ts") or (has("order_id", "pay_amount")): return "payments"
        if anyof("product_name", "product_id") and anyof("amount", "qty", "unit_price"): return "lines"
        if has("order_id") and anyof("status", "total_due", "goods_total", "debt", "order_date"): return "orders"
        if has("supplier_id") and not anyof("customer_id", "receipt_id"): return "suppliers"
        if has("staff_id") and not anyof("customer_id", "order_id"): return "staff"
        if anyof("customer_id", "phone", "cust_group", "address") and not anyof("product_id", "base_unit", "price"): return "customers"
        if anyof("name", "product_name") and anyof("product_id", "base_unit", "group", "price", "cost"): return "products"
        if has("supplier_id", "name"): return "suppliers"
        if has("staff_id", "name"): return "staff"
        return "other"

    def _build(self):
        logical = {n: self._clean(df) for n, df in self._logical().items()}
        t = defaultdict(list)
        for n, df in logical.items():
            t[self._kind(df.columns)].append(df.assign(_src=n))
        t = {k: pd.concat(v, ignore_index=True) for k, v in t.items()}
        self._finish(t)
        return t

    # ---------- building the canonical tables ----------
    def _finish(self, t):
        conv_rows = []
        if "conv" in t:
            c = t["conv"]
            for _, r in c.iterrows():
                conv_rows.append({"product_id": r.get("product_id"), "pkey": P.key(r.get("product_name") or r.get("name")),
                                  "unit": r.get("big_unit"), "factor": r.get("factor"), "base_unit": r.get("base_unit")})
        for name, big, f, base in self.readme["conversions"]:
            conv_rows.append({"product_id": None, "pkey": P.key(name), "unit": big, "factor": f, "base_unit": base})
        t["conv"] = pd.DataFrame(conv_rows, columns=["product_id", "pkey", "unit", "factor", "base_unit"])

        if "products" in t:
            p = t["products"].copy()
            if "name" not in p and "product_name" in p:
                p["name"] = p["product_name"]
            p["pkey"] = p["name"].map(P.key)
            t["products"] = p.drop_duplicates("product_id" if "product_id" in p else "pkey")

        if "purchase_lines" in t:  # the shared README says 'đơn vị tính', 'số lượng' for purchase lines
            pl = t["purchase_lines"]
            t["purchase_lines"] = pl.rename(columns={c: "in_" + c for c in ("unit", "qty") if c in pl and "in_" + c not in pl})
        if "lines" in t and "products" in t and "alias" in t["products"]:  # ledger with abbreviated product names: map to full names
            p = t["products"]
            full = {P.key(a): n for a, n in zip(p["alias"], p["name"]) if not P.is_blank(a)}
            t["lines"]["product_name"] = t["lines"]["product_name"].map(lambda v: full.get(P.key(v), v))
        if "lines" in t:
            t["lines"] = self._lines(t)
        if "orders" in t or "lines" in t:
            t["orders"] = self._orders(t)

    def _lines(self, t):
        L = t["lines"].copy()
        if "order_id" in L:
            L = L.drop_duplicates(subset=[c for c in L.columns if c not in ("_src", "_sheet")])  # duplicate within the same order = export error
        else:
            L["order_id"] = [f"_row{i}" for i in range(len(L))]  # ledger without order ids: each row is one entry
        if "product_name" in L:  # voucher / points / shipping-fee rows written like products: not goods sold (rulebook §1)
            L = L[~L["product_name"].astype(str).str.strip().str.lower().str.match(r"(voucher|dùng \d* ?điểm|điểm tích|phí ship|phí giao|ship)\b")]
        L["pkey"] = L["product_name"].map(P.key) if "product_name" in L else ""
        prods = t.get("products")
        if prods is not None and "product_id" in prods:
            if "product_id" not in L and "product_name" in L:  # join by name
                L["product_id"] = L["pkey"].map(dict(zip(prods["pkey"], prods["product_id"])))
            if "product_name" not in L or L["product_name"].isna().all():
                L["product_name"] = L["product_id"].map(dict(zip(prods["product_id"], prods["name"])))
                L["pkey"] = L["product_name"].map(P.key)
        if "unit" not in L and "_qty_unit" in L:
            L["unit"] = L["_qty_unit"]
        elif "_qty_unit" in L:
            L["unit"] = L["unit"].fillna(L["_qty_unit"])
        if "qty_base" not in L or L["qty_base"].isna().any():
            L["qty_base"] = self._to_base(L, t["conv"])
        if "amount" not in L and {"qty", "unit_price"} <= set(L.columns):
            d = "line_discount" if "line_discount" in L else "discount"
            L["amount"] = L["qty"] * L["unit_price"] - (L[d].fillna(0) if d in L else 0)
        return L

    @staticmethod
    def _to_base(L, conv):
        byid = {(r.product_id, P.key(r.unit)): r.factor for r in conv.itertuples() if r.product_id}
        byname = {(r.pkey, P.key(r.unit)): r.factor for r in conv.itertuples() if r.pkey}
        out = []
        for r in L.itertuples():
            if "qty_base" in L and not P.is_blank(getattr(r, "qty_base", None)):
                out.append(r.qty_base)
                continue
            u = P.key(getattr(r, "unit", None))
            f = byid.get((getattr(r, "product_id", None), u)) or byname.get((r.pkey, u)) or 1
            q = getattr(r, "qty", None)
            out.append(None if q is None else q * f)
        return out

    def _orders(self, t):
        L = t.get("lines")
        O = t.get("orders")
        had_status = (L is not None and "status" in L) or (O is not None and "status" in O)
        if L is not None:
            first_date = lambda s: min((d for d in s if isinstance(d, dt.date)), default=None)  # drop empty date cells (NaN)
            agg = {"order_date": first_date} if "order_date" in L else {}
            # order-level columns repeated on every row of the order (restaurant, POS): move them to the orders table
            for c in ("status", "customer_name", "customer_id", "order_ts", "_order_ts2") + ORDER_FIELDS:
                if c in L:
                    agg[c] = "first"
            g = L.groupby("order_id", sort=False)
            fromL = g.agg(agg) if agg else pd.DataFrame(index=g.size().index)
            fromL["revenue_lines"] = g["amount"].sum(min_count=1) if "amount" in L else None
            if "qty" in L:  # hand ledger: negative-quantity rows with the same order id = order with a return
                neg = pd.to_numeric(L["qty"], errors="coerce").groupby(L["order_id"], sort=False).min() < 0  # qty column may contain text
                fromL.loc[neg[neg].index, "status"] = "tra_hang"
            fromL = fromL.reset_index()
            if O is None:
                O = fromL
            else:
                O = O.drop_duplicates("order_id")
                miss = [c for c in fromL.columns if c not in O.columns or c == "revenue_lines"]
                O = O.drop(columns=[c for c in miss if c in O and c != "order_id"]).merge(
                    fromL[["order_id"] + [c for c in miss if c != "order_id"]], on="order_id", how="left")
        O = O.copy()
        if "trade_ins" in t and "trade_in" not in O:  # separate trade-in ledger, order number written in the sales ledger
            T = t["trade_ins"]
            O["trade_in"] = O["order_id"].map(T.groupby("order_id")["trade_in"].sum())
        if not had_status and "note" in O:  # ledger without a status column: status is written in the Notes (rulebook §8)
            n = O["note"].map(lambda v: "" if P.is_blank(v) else str(v).lower())
            O.loc[n.str.contains(r"trả lại|mang trả|trả hàng"), "status"] = "tra_hang"
            O.loc[n.str.contains(r"hu[ỷy]|cancel"), "status"] = "huy"
        if not had_status:  # shop does not record status: sold orders are completed (except orders with a return row above)
            O["status"] = O["status"].fillna("hoan_thanh") if "status" in O else "hoan_thanh"
        if "order_date" in O:  # unreadable date cell (NaN) → None so date comparisons do not fail
            O["order_date"] = O["order_date"].map(lambda d: d if isinstance(d, dt.date) else None)
        if "order_ts" not in O and "_order_ts2" in O:
            O["order_ts"] = O["_order_ts2"]
        if "order_date" not in O and "order_ts" in O:
            O["order_date"] = O["order_ts"].map(lambda x: x.date() if pd.notna(x) else None)
        if "revenue_lines" not in O or O["revenue_lines"].isna().all():
            O["revenue_lines"] = O.get("goods_total")  # shop has invoices only: goods total = sum of line amounts
        cid = O["customer_id"] if "customer_id" in O else pd.Series(None, index=O.index)
        cname = O["customer_name"] if "customer_name" in O else pd.Series(None, index=O.index)
        O["is_walkin"] = [P.is_blank(i) and (P.is_blank(n) or P.is_walkin(n)) for i, n in zip(cid, cname)]
        if "customer_id" in O and O["customer_id"].notna().any():
            O["cust"] = O["customer_id"].where(~O["is_walkin"])
        else:
            O["cust"] = cname.map(lambda n: P.key(P.strip_phone(n))).where(~O["is_walkin"])
        return O

    def _meta(self):
        O = self.t.get("orders")
        ds = [d for d in O["order_date"] if isinstance(d, dt.date)] if O is not None and "order_date" in O else []
        self.data_start = min(ds) if ds else None  # unreadable date cell is NaN (float): skip
        self.has = set(self.t)

    def __repr__(self):
        return f"Shop({self.id}, {self.data_start}→{self.data_end}, {sorted((k, len(v)) for k, v in self.t.items())})"


def _load_one(args):
    import time
    root, b, fresh = args
    t0 = time.time()
    s = Shop(root / b, root, use_cache=not fresh)
    return f"{s!r}  {time.time() - t0:.0f}s"


if __name__ == "__main__":
    import sys
    from multiprocessing import Pool
    fresh = "--fresh" in sys.argv
    argv = [a for a in sys.argv[1:] if a != "--fresh"]
    root = Path(argv[0] if argv else "train/data")
    ids = argv[1:] or sorted(p.name for p in root.iterdir() if p.is_dir())
    with Pool(min(6, os.cpu_count() or 1)) as pool:
        for line in pool.imap(_load_one, [(root, b, fresh) for b in ids]):
            print(line, flush=True)
