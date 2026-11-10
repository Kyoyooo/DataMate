"""Tool catalog for the LLM (step 3) and the executor.

The LLM only picks one tool and fills JSON parameters; every computation is done by the rules library (rules.py).
Periods are structured data (PERIOD_SCHEMA) so the code converts them exactly per rulebook §2.
"""
import datetime as dt
import difflib
import os
from pathlib import Path

from . import parse as P
from . import period as T
from . import rules as R
from . import industry as I
from .entity import find_product, products

# ---------- periods ----------
PERIOD_TYPES = ["day", "today", "yesterday", "this_week", "last_week", "this_month", "last_month", "month", "quarter",
                "year", "ytd", "last_n_days", "range", "tet"]
def _obj(props, required):
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


# One branch per type, required fields first: constrained decoding writes fields in declaration order,
# a flat schema made the model write year first and never come back to fill month (it filled quarter by mistake).
_I, _S = {"type": "integer"}, {"type": "string"}
PERIOD_SCHEMA = {"anyOf": [
    _obj({"type": {"enum": ["today", "yesterday", "this_week", "last_week", "this_month", "last_month", "ytd"]}}, ["type"]),
    _obj({"type": {"const": "day"}, "date": _S}, ["type", "date"]),
    _obj({"type": {"const": "month"}, "month": _I, "year": _I}, ["type", "month"]),
    _obj({"type": {"const": "quarter"}, "quarter": _I, "year": _I}, ["type", "quarter"]),
    _obj({"type": {"const": "year"}, "year": _I}, ["type"]),
    _obj({"type": {"const": "last_n_days"}, "n": _I}, ["type", "n"]),
    _obj({"type": {"const": "range"}, "start": _S, "end": _S}, ["type", "start", "end"]),
    _obj({"type": {"const": "tet"}, "year": _I}, ["type"]),
]}
_t = [b["properties"]["type"] for b in PERIOD_SCHEMA["anyOf"]]
assert sorted(t.get("const") or x for t in _t for x in t.get("enum", [None])) == sorted(PERIOD_TYPES)  # covers every type resolve() understands


def _d(s):
    return dt.date.fromisoformat(s)


def resolve(spec, today):
    """Structured period → Period per the rulebook."""
    t = spec["type"]
    if t == "day":
        return T.day(_d(spec["date"]))
    if t == "today":
        return T.day(today)
    if t == "yesterday":
        return T.day(today - dt.timedelta(days=1))
    if t == "this_week":
        return T.this_week(today)
    if t == "last_week":
        return T.last_week(today)
    if t == "this_month":
        return T.this_month(today)
    if t == "last_month":
        return T.previous(T.month(today.year, today.month))
    if t == "month":
        return T.month(spec["year"], spec["month"]) if spec.get("year") else T.month_no_year(today, spec["month"])
    if t == "quarter":
        return T.quarter(spec["year"], spec["quarter"]) if spec.get("year") else T.quarter_no_year(today, spec["quarter"])
    if t == "year":
        return T.year(spec.get("year") or today.year)
    if t == "ytd":
        return T.ytd(today)
    if t == "last_n_days":
        return T.last_n_days(today, spec["n"])
    if t == "range":
        return T.Period(_d(spec["start"]), _d(spec["end"]), "range")
    if t == "tet":
        return T.tet(spec.get("year") or today.year, _calendar())
    raise ValueError(t)


def _calendar():
    return os.environ.get("DATAMATE_CALENDAR") or Path(__file__).resolve().parent.parent / "train/calendar.csv"


def compare_period(cur, how, spec2, today):
    if how == "same_period_last_month":  # from day 1 to the same day number of the previous month, even when the model gave the period as a range
        return T.previous(T.Period(cur.start, cur.end, "this_month"))
    if how == "same_period_last_year":
        return T.same_period_last_year(cur)
    if how == "before_tet":
        return T.before_tet(cur)
    if how == "last_year_tet":  # Lunar New Year of the previous year, a different solar date
        return T.tet(cur.end.year - 1, _calendar())
    if how == "other" and spec2:
        return resolve(spec2, today)
    return T.previous(cur)


# ---------- entity lookup ----------
def product_key(shop, name):
    if not name:
        raise R.Unanswerable("thiếu tên mặt hàng")
    hit = find_product(shop, name)
    if hit:
        return hit[0]
    names = {P.key(nm): k for k, (_, nm) in products(shop).items()}
    m = difflib.get_close_matches(P.key(name), list(names), n=1, cutoff=0.85)
    if m:
        return names[m[0]]
    raise R.Unanswerable(f"không thấy mặt hàng '{name}'")


def staff_id(shop, x):
    """Staff code or name (with/without accents) → code."""
    St = shop.t.get("staff")
    names = {P.key(n): i for i, n in zip(St["staff_id"], St["name"])} if St is not None and "name" in St else {}
    hit = names.get(P.key(x)) or next((i for i in names.values() if P.key(i) == P.key(x)), None)
    if hit is None and names:
        raise R.Unanswerable(f"không có nhân viên {x}")
    return hit or str(x).upper()


def customer_key(shop, name):
    if not name:
        return None
    c = R.find_customer(shop, name)
    if c is None:
        raise R.Unanswerable(f"không thấy khách '{name}'")
    return c


def _num(v):
    return {"type": "number", "answer": v}


def _pct(v):
    return {"type": "percent", "answer": v}


# ---------- catalog: name → (description, parameters, function) ----------
def _per(a, today):
    return resolve(a["period"], today)


TOOLS = {
    "revenue": ("Doanh thu (tiền bán, thu về) của cả cửa hàng trong kỳ", ["period"],
                lambda s, a, t: _num(R.revenue(s, _per(a, t)))),
    "revenue_change_pct": ("% thay đổi doanh thu kỳ hỏi so với kỳ so (compare: previous | same_period_last_month | same_period_last_year | before_tet | last_year_tet | other+period2)",
                           ["period", "compare", "period2"],
                           lambda s, a, t: _pct(R.pct_change(R.revenue(s, _per(a, t)), R.revenue(s, compare_period(_per(a, t), a.get("compare"), a.get("period2"), t))))),
    "revenue_by_month": ("Doanh thu từng tháng theo thứ tự (months: [[năm, tháng], ...]) → list", ["months"],
                         lambda s, a, t: {"type": "list", "answer": R.monthly_revenue(s, a["months"])}),
    "best_month": ("Tháng có doanh thu cao nhất trong các tháng (months) → YYYY-MM", ["months"],
                   lambda s, a, t: {"type": "date", "answer": R.best_month(s, a["months"])}),
    "revenue_increasing": ("Doanh thu các tháng (months) có tăng liên tục không → boolean", ["months"],
                           lambda s, a, t: {"type": "boolean", "answer": R.increasing(s, a["months"])}),
    "order_count": ("Số đơn (không huỷ, không trả) trong kỳ", ["period"], lambda s, a, t: _num(R.order_count(s, _per(a, t)))),
    "cancel_count": ("Số đơn bị huỷ trong kỳ", ["period"], lambda s, a, t: _num(R.cancel_count(s, _per(a, t)))),
    "cancel_rate": ("Tỉ lệ % đơn huỷ trong kỳ", ["period"], lambda s, a, t: _pct(R.cancel_rate(s, _per(a, t)))),
    "avg_order_value": ("Doanh thu trung bình một đơn (cust_group tuỳ chọn: sỉ | lẻ | thân thiết). Cửa hàng điện thoại hỏi 'khách phải trả' → dt_total_due", ["period", "cust_group"],
                        lambda s, a, t: _num(R.avg_order_value(s, _per(a, t), a.get("cust_group")))),
    "best_day": ("Ngày có doanh thu cao nhất trong kỳ → YYYY-MM-DD", ["period"], lambda s, a, t: {"type": "date", "answer": R.best_day(s, _per(a, t))}),
    "orders_at_least": ("Số đơn có doanh thu ≥ amount", ["period", "amount"], lambda s, a, t: _num(R.orders_with_revenue_at_least(s, _per(a, t), a["amount"]))),
    "days_at_least": ("Số ngày có doanh thu ≥ amount", ["period", "amount"], lambda s, a, t: _num(R.days_with_revenue_at_least(s, _per(a, t), a["amount"]))),
    "product_revenue": ("Doanh thu (tiền bán) của một mặt hàng", ["period", "product"],
                        lambda s, a, t: _num(R.product_revenue(s, _per(a, t), product_key(s, a["product"])))),
    "product_qty": ("Số lượng bán (đơn vị cơ bản) của một mặt hàng", ["period", "product"],
                    lambda s, a, t: _num(R.product_qty(s, _per(a, t), product_key(s, a["product"])))),
    "qty_by_unit": ("Tổng số lượng bán của mọi mặt hàng có đơn vị cơ bản là unit (ly, lon, bình...)", ["period", "unit"],
                    lambda s, a, t: _num(R.qty_by_base_unit(s, _per(a, t), a["unit"]))),
    "size_qty": ("Số ly size M hoặc L bán được, cộng mọi món (size: M | L)", ["period", "size"],
                 lambda s, a, t: _num(R.size_qty(s, _per(a, t), a["size"]))),
    "top_products": ("Mặt hàng bán chạy (by: qty) / doanh thu (revenue) / lời nhất (profit). k=1 và hỏi 'nhất' → một tên",
                     ["period", "k", "by", "single"], lambda s, a, t: _top_products(s, a, t)),
    "top_customers": ("Xếp hạng khách. by: revenue (mua nhiều tiền nhất, mặc định) | orders (nhiều đơn nhất) | days (trung thành: nhiều ngày có mua nhất) | aov (sộp: TB một đơn cao nhất, khách ≥3 đơn) | cancels (đổi ý: huỷ nhiều đơn nhất)", ["period", "k", "by", "single"],
                      lambda s, a, t: _single_or_list(R.top_customers(s, _per(a, t), a.get("k") or 1, a.get("by") or "revenue"), a)),
    "buyers_min_orders": ("Số khách (hoặc % khách đã mua nếu as_percent) có từ n đơn trở lên", ["period", "n", "as_percent"],
                          lambda s, a, t: _pct(R.pct_buyers_with_min_orders(s, _per(a, t), a["n"])) if a.get("as_percent") else _num(R.buyers_with_min_orders(s, _per(a, t), a["n"]))),
    "staff_revenue": ("Doanh thu của nhân viên (staff: mã NV001... hoặc tên)", ["period", "staff"], lambda s, a, t: _staff_rev(s, a, t)),
    "best_staff": ("Nhân viên có doanh thu cao nhất → mã", ["period"],
                   lambda s, a, t: {"type": "string", "answer": R._rank(R.staff_revenue(s, _per(a, t)), 1)["id"].iloc[0]}),
    "revenue_by_payment": ("Doanh thu theo hình thức thanh toán ghi trên đơn (values: cash = tiền mặt/tm | transfer = chuyển khoản/ck | ewallet = ví điện tử/ví/momo/zalopay (KHÁC chuyển khoản) | cod | debt = ghi nợ; nhiều giá trị → list đúng thứ tự nêu trong câu hỏi). as_percent → % trên tổng",
                           ["period", "values", "as_percent"], lambda s, a, t: _by_attr(s, a, t, "pay_method")),
    "revenue_by_channel": ("Doanh thu theo kênh bán (values: store = tại quầy/tại cửa hàng/tại tiệm | phone = điện thoại | zalo_oa)", ["period", "values", "as_percent"],
                           lambda s, a, t: _by_attr(s, a, t, "channel")),
    "revenue_by_cust_group": ("Doanh thu theo nhóm khách (values: sỉ|lẻ|thân thiết)", ["period", "values", "as_percent"],
                              lambda s, a, t: _by_attr(s, a, t, "cust_group")),
    "group_revenue": ("Doanh thu một nhóm HÀNG (group đúng tên nhóm hàng; nhóm KHÁCH như thân thiết/sỉ/lẻ → revenue_by_cust_group); as_percent → tỉ trọng trên doanh thu cả shop", ["period", "group", "as_percent"],
                      lambda s, a, t: _share_or_num(s, a, t, R.group_revenue(s, _per(a, t), a["group"]))),
    "rx_revenue": ("Doanh thu thuốc kê đơn (rx=true) hoặc hàng không kê đơn (rx=false); as_percent → tỉ trọng", ["period", "rx", "as_percent"],
                   lambda s, a, t: _share_or_num(s, a, t, R.rx_revenue(s, _per(a, t), a.get("rx", True)))),
    "ingredient_revenue": ("Doanh thu các thuốc có đúng hoạt chất ingredient", ["period", "ingredient"],
                           lambda s, a, t: _num(R.ingredient_revenue(s, _per(a, t), a["ingredient"]))),
    "shift": ("Ca sáng/chiều: metric revenue|orders; hỏi riêng một ca → shift sang|chieu; chỉ khi so ca chiều với ca sáng (%) → compare_shift=true", ["period", "metric", "shift", "compare_shift"],
              lambda s, a, t: _shift(s, a, t)),
    "purchase_total": ("Tổng tiền nhập hàng (phiếu nhập) trong kỳ", ["period"], lambda s, a, t: _num(R.purchase_total(s, _per(a, t)))),
    "avg_import_price": ("Giá nhập bình quân một đơn vị nhập (unit) của mặt hàng trong kỳ", ["period", "product", "unit"],
                         lambda s, a, t: _num(R.avg_import_price(s, _per(a, t), product_key(s, a["product"]), a.get("unit")))),
    "top_supplier": ("Nhà cung cấp đứng đầu. by: amount (tổng tiền nhập cao nhất, mặc định) | count (nhập nhiều phiếu nhất, 'nhà cung cấp chính')", ["period", "by"],
                     lambda s, a, t: {"type": "string", "answer": R.top_supplier(s, _per(a, t), "count" if a.get("by") == "count" else "amount")}),
    "group_top_product": ("Mặt hàng đứng đầu trong một nhóm HÀNG (by: qty bán chạy | revenue doanh thu cao nhất)", ["period", "group", "by"],
                          lambda s, a, t: {"type": "string", "answer": R.group_top_product(s, _per(a, t), a["group"], "revenue" if a.get("by") == "revenue" else "qty")}),
    "group_order_count": ("Số đơn có ít nhất một mặt hàng của nhóm HÀNG", ["period", "group"], lambda s, a, t: _num(R.group_order_count(s, _per(a, t), a["group"]))),
    "group_qty": ("Tổng số lượng bán của nhóm HÀNG", ["period", "group"], lambda s, a, t: _num(R.group_qty(s, _per(a, t), a["group"]))),
    "busiest_day": ("Ngày đông khách / nhiều đơn nhất trong kỳ → YYYY-MM-DD (khác best_day: doanh thu cao nhất)", ["period"],
                    lambda s, a, t: {"type": "date", "answer": R.busiest_day(s, _per(a, t))}),
    "peak_hour": ("Khung giờ (số giờ 0–23) có nhiều đơn nhất", ["period"], lambda s, a, t: _num(R.peak_hour(s, _per(a, t)))),
    "most_ordered_product": ("Mặt hàng được ưa chuộng nhất: có mặt trong nhiều đơn nhất", ["period"],
                             lambda s, a, t: {"type": "string", "answer": R.most_ordered_product(s, _per(a, t))}),
    "buyers_count": ("Số khách (khác nhau) đã mua trong kỳ", ["period"], lambda s, a, t: _num(R.buyers_count(s, _per(a, t)))),
    "in_minus_out": ("Số nhập trừ số bán của mặt hàng (đơn vị cơ bản)", ["period", "product"],
                     lambda s, a, t: _num(R.in_minus_out(s, _per(a, t), product_key(s, a["product"])))),
    "debt_total": ("Tổng SỐ TIỀN khách còn nợ tính đến hết ngày date ('còn nợ tổng cộng bao nhiêu tiền'; customer tuỳ chọn)", ["date", "customer"], lambda s, a, t: _debt_total(s, a, t)),
    "debtors_count": ("Đếm SỐ KHÁCH (số người) còn nợ đến hết ngày date; hỏi số tiền nợ thì dùng debt_total", ["date"], lambda s, a, t: _num(R.debtors_count(s, _date(a, t)))),
    "top_debtors": ("Bảng k khách nợ nhiều nhất đến hết ngày date", ["date", "k"],
                    lambda s, a, t: {"type": "table", "answer": R.top_debtors(s, _date(a, t), a.get("k") or 3)}),
    "debt_aging": ("Tiền nợ theo nhóm tuổi nợ, buckets [[0,7],[8,15],[16,null]]", ["date", "buckets"],
                   lambda s, a, t: {"type": "list", "answer": R.debt_aging(s, _date(a, t), [tuple(b) for b in a["buckets"]])}),
    "overdue_debt": ("Tiền còn nợ của các đơn đặt đã hơn n ngày", ["date", "n"], lambda s, a, t: _num(R.overdue_debt(s, _date(a, t), a["n"]))),
    "debt_collected": ("Tiền khách trả nợ (thu nợ) trong kỳ (customer tuỳ chọn)", ["period", "customer"],
                       lambda s, a, t: _num(R.debt_collected(s, _per(a, t), customer_key(s, a.get("customer"))))),
    "debt_new_and_paid": ("[nợ thêm, trả nợ] trong kỳ của một khách", ["period", "customer"],
                          lambda s, a, t: {"type": "list", "answer": [R.new_debt(s, _per(a, t), customer_key(s, a.get("customer"))),
                                                                       R.debt_collected(s, _per(a, t), customer_key(s, a.get("customer")))]}),
    "stock": ("Tồn kho (đơn vị cơ bản) của mặt hàng lúc hết ngày date. Chỉ khi hỏi 'mấy hộp chẵn, mấy gói lẻ' mới điền big_unit = tên đơn vị lớn (vd hộp) → [số hộp, số lẻ]", ["date", "product", "big_unit"],
              lambda s, a, t: _stock(s, a, t)),
    "stock_value": ("Giá trị hàng tồn kho theo giá vốn lúc hết ngày date", ["date"], lambda s, a, t: _num(R.stock_value(s, _date(a, t)))),
    "out_of_stock_count": ("Số mặt hàng hết hàng lúc hết ngày date", ["date"], lambda s, a, t: _num(R.out_of_stock_count(s, _date(a, t)))),
    "nearest_expiry": ("Hạn dùng của lô gần hết hạn nhất còn tồn của mặt hàng → YYYY-MM-DD", ["date", "product"],
                       lambda s, a, t: {"type": "date", "answer": R.nearest_expiry(s, _date(a, t), product_key(s, a["product"]))}),
    "lots_left": ("Số lô còn tồn của mặt hàng", ["date", "product"], lambda s, a, t: _num(R.lots_left(s, _date(a, t), product_key(s, a["product"])))),
    "expiring": ("Lô còn tồn có hạn dùng trong [start, end]; mode: products (list tên) | count_products | count_lots | value (tiền vốn)",
                 ["start", "end", "mode"], lambda s, a, t: _expiring(s, a, t)),
    "price_on": ("Giá bán một đơn vị cơ bản của mặt hàng ngày date", ["date", "product"],
                 lambda s, a, t: _num(R.price_on(s, _d(a["date"]), product_key(s, a["product"])))),
    "price_effect": ("% thay đổi số lượng bán n ngày kể từ ngày tăng giá date so với n ngày ngay trước. date chỉ điền khi câu hỏi ghi rõ ngày; không ghi ngày → bỏ date, điền new_price (giá mới)",
                     ["product", "date", "n", "new_price"], lambda s, a, t: _price_effect(s, a, t)),
    "unsold_count": ("Số mặt hàng đã từng bán trước kỳ nhưng trong kỳ không bán được (ế)", ["period"], lambda s, a, t: _num(R.unsold_count(s, _per(a, t)))),
    "products_in_orders": ("Số mặt hàng xuất hiện trong ít nhất n đơn khác nhau", ["period", "n"],
                           lambda s, a, t: _num(R.products_in_min_orders(s, _per(a, t), a["n"]))),
    "gross_profit": ("Lãi gộp của cửa hàng trong kỳ", ["period"], lambda s, a, t: _num(R.gross_profit(s, _per(a, t)))),
    "net_profit": ("Lãi ròng (lãi gộp trừ mọi chi phí) trong kỳ", ["period"], lambda s, a, t: _num(R.net_profit(s, _per(a, t)))),
    "delivered_qty": ("Vật liệu xây dựng: số lượng một mặt hàng ĐÃ GIAO/CHỞ ĐI tính đến hết ngày date cho các đơn ĐẶT trong kỳ period", ["period", "date", "product"],
                      lambda s, a, t: _num(R.delivered_qty(s, _per(a, t), _date(a, t), product_key(s, a["product"])))),
    "orders_min_deliveries": ("Vật liệu xây dựng: số đơn ĐẶT trong kỳ period đã được giao từ n đợt trở lên tính đến hết ngày date", ["period", "date", "n"],
                              lambda s, a, t: _num(R.orders_min_deliveries(s, _per(a, t), _date(a, t), a["n"]))),
    "credit_due_count": ("Bán chịu: số đơn đặt đến hết ngày date có ngày phải trả nằm trong kỳ period; KHÔNG có period → số đơn có hạn trả sau ngày date", ["date", "period"],
                         lambda s, a, t: _num(R.credit_due_count(s, _date(a, t), _per(a, t) if a.get("period") else None))),
    "delivery_count": ("Số đợt giao hàng có ngày giao trong kỳ", ["period"], lambda s, a, t: _num(R.delivery_count(s, _per(a, t)))),
    # ---- motorbike repair (ledger with a bike / plate column) ----
    "sx_commission": ("Sửa xe: hoa hồng thợ. staff → của một thợ; what=table → bảng hoa hồng mọi thợ; what=top → thợ hoa hồng cao nhất", ["period", "staff", "what"],
                      lambda s, a, t: I.repair_commission(s, _per(a, t), _staff_name(s, a.get("staff")), a.get("what"))),
    "sx_job_count": ("Sửa xe: số lượt xe có làm một việc (job: sửa điện, vá ruột/vá xe, nhớt láp/hộp số, rửa xe, kim phun, bugi, curoa, lọc gió, nước mát, ắc quy, bóng đèn)", ["period", "job"],
                     lambda s, a, t: I.repair_job_count(s, _per(a, t), I.job_pattern(a["job"]))),
    "sx_avg_ticket": ("Sửa xe: tiền trung bình một phiếu (không tính phiếu bảo hành)", ["period"], lambda s, a, t: I.repair_avg_ticket(s, _per(a, t))),
    "sx_warranty": ("Sửa xe: số phiếu bảo hành; as_percent → % so với phiếu thu tiền", ["period", "as_percent"], lambda s, a, t: I.repair_warranty(s, _per(a, t), bool(a.get("as_percent")))),
    "sx_staff": ("Sửa xe: của một thợ, what=revenue (tiền) | turns (số lượt xe)", ["period", "staff", "what"],
                 lambda s, a, t: I.repair_staff(s, _per(a, t), _staff_name(s, a.get("staff")), a.get("what"))),
    "sx_top_staff": ("Sửa xe: thợ đứng đầu, what=days (chăm chỉ: nhiều ngày làm nhất) | revenue (nhiều tiền nhất) | turns (nhiều lượt xe nhất)", ["period", "what"],
                     lambda s, a, t: I.repair_top_staff(s, _per(a, t), a.get("what"))),
    "sx_top_model": ("Sửa xe: dòng xe mang về nhiều tiền nhất", ["period"], lambda s, a, t: I.repair_top_model(s, _per(a, t))),
    "sx_repeat": ("Sửa xe: số xe (biển số) đến từ n lần trở lên; 'khách quen' = 2", ["period", "n"], lambda s, a, t: I.repair_repeat_vehicles(s, _per(a, t), a.get("n") or 2)),
    "sx_model_vehicles": ("Sửa xe: số chiếc xe khác nhau (biển số) của một dòng xe (model, vd Wave, Air Blade)", ["period", "model"],
                          lambda s, a, t: I.repair_model_vehicles(s, _per(a, t), a["model"])),
    "sx_weekday_avg": ("Sửa xe: số lượt xe trung bình mỗi ngày thứ weekday (thứ 2 … thứ 7, chủ nhật) trong kỳ", ["period", "weekday"],
                       lambda s, a, t: I.repair_weekday_avg(s, _per(a, t), I.WEEKDAY[I.norm(a["weekday"])])),
    "sx_ticket_count": ("Sửa xe: tổng số phiếu / lượt xe trong kỳ", ["period"], lambda s, a, t: I.repair_ticket_count(s, _per(a, t))),
    # ---- phone shop (ledger with IMEI) ----
    "dt_installment": ("Điện thoại, sổ TRẢ GÓP đến hết ngày date. Có customer: what=due_periods (số kỳ đã tới hạn) | remaining (còn thiếu). Cả shop: what=remaining (còn phải góp) | overdue (tiền góp quá hạn) | overdue_customers (số khách góp chậm)",
                       ["date", "customer", "what"], lambda s, a, t: I.phone_installment(s, _date(a, t), a.get("what"), a.get("customer"))),
    "dt_debt": ("Điện thoại, sổ NỢ + góp còn nợ đến hết ngày date: what=total (tổng tiền) | debtors (số khách) | aging (theo tuổi nợ, buckets [[0,30],[31,60],[61,null]])",
                ["date", "what", "buckets"], lambda s, a, t: I.phone_debt(s, _date(a, t), a.get("what"), a.get("buckets"))),
    "dt_trade_in": ("Điện thoại: tiền thu lại máy cũ của khách; as_percent → % số đơn có thu máy cũ", ["period", "as_percent"],
                    lambda s, a, t: I.phone_trade_in(s, _per(a, t), bool(a.get("as_percent")))),
    "dt_total_due": ("Điện thoại: tổng tiền khách phải trả (sau trừ máy cũ); avg=true → trung bình một đơn", ["period", "avg"],
                     lambda s, a, t: I.phone_total_due(s, _per(a, t), bool(a.get("avg")))),
    "dt_warranty": ("Điện thoại, bảo hành: what=count (số lượt bảo hành trong kỳ) | pct_sold (% lượt bảo hành trên số máy bán) | top_model (dòng máy bảo hành nhiều nhất) | sold_seen (số máy bán trong kỳ đã mang tới bảo hành tính đến hôm nay)",
                    ["period", "what"], lambda s, a, t: I.phone_warranty(s, _per(a, t), t, a.get("what"))),
    "dt_top_family": ("Điện thoại: dòng máy bán chạy nhất (theo số máy); k → list k dòng", ["period", "k"],
                      lambda s, a, t: I.phone_top_family(s, _per(a, t), a.get("k") if (a.get("k") or 1) > 1 else None)),
    "dt_top_in_group": ("Điện thoại: máy bán chạy nhất trong nhóm máy mới (what=new) / máy cũ (what=old)", ["period", "what"],
                        lambda s, a, t: I.phone_top_in_group(s, _per(a, t), a.get("what"))),
    "dt_share": ("Điện thoại, %: what=brand_units (% số máy bán là của hãng brand) | new_revenue (% doanh thu máy mới trên doanh thu máy)", ["period", "what", "brand"],
                 lambda s, a, t: I.phone_share(s, _per(a, t), a.get("what"), a.get("brand"))),
    "dt_avg_price": ("Điện thoại: giá bán trung bình một máy; what=old → chỉ máy cũ", ["period", "what"],
                     lambda s, a, t: I.phone_avg_price(s, _per(a, t), a.get("what") == "old")),
    "dt_units": ("Điện thoại: số máy bán; what=old/new lọc máy cũ/mới; family (dòng máy, vd iPhone 15) hoặc brand (hãng) lọc thêm", ["period", "what", "family", "brand"],
                 lambda s, a, t: I.phone_units(s, _per(a, t), a.get("what"), a.get("family"), a.get("brand"))),
    # ---- mother & baby (catalog with Số / Size, Hãng) ----
    "mb_new_members": ("Mẹ và bé: số khách đăng ký thành viên mới", ["period"], lambda s, a, t: I.mb_new_members(s, _per(a, t))),
    "mb_extra": ("Mẹ và bé: tổng tiền trên hoá đơn của what=voucher | points (dùng điểm) | ship (phí ship)", ["period", "what"],
                 lambda s, a, t: I.mb_extra(s, _per(a, t), a.get("what"))),
    "mb_diaper": ("Mẹ và bé: số bỉm/tã bán của MỘT size (diaper_size NB|S|M|L|XL|XXL) HOẶC MỘT hãng (brand); as_percent → % trên mọi bỉm", ["period", "diaper_size", "brand", "as_percent"],
                  lambda s, a, t: I.mb_diaper(s, _per(a, t), a.get("diaper_size"), a.get("brand"), bool(a.get("as_percent")))),
    "mb_milk": ("Mẹ và bé: sữa bột số stage (1, 2, 3, 4): what=qty (số lon bán) | top_brand (hãng bán chạy nhất theo số lon) | top_brand_revenue (hãng doanh thu cao nhất)", ["period", "stage", "what"],
                lambda s, a, t: I.mb_milk_qty(s, _per(a, t), a["stage"]) if a.get("what", "qty") == "qty"
                else I.mb_milk_top_brand(s, _per(a, t), a["stage"], "revenue" if a.get("what") == "top_brand_revenue" else "qty")),
    "unanswerable": ("Dữ liệu không có thông tin cần (câu chủ quan, giới tính, địa chỉ, lý do...)", ["reason"],
                     lambda s, a, t: {"type": "unanswerable", "reason": a.get("reason", "")}),
    "abstain": ("Không hiểu câu hỏi / không có công cụ phù hợp", [], lambda s, a, t: {"type": "abstain"}),
}


def _staff_rev(s, a, t):
    if "vehicle" in s.t["lines"]:  # motorbike repair shop: mechanic revenue from the ticket ledger
        return I.repair_staff(s, _per(a, t), _staff_name(s, a.get("staff")), "revenue")
    return _num(int(round(R.staff_revenue(s, _per(a, t)).get(staff_id(s, a.get("staff")), 0))))


def _staff_name(shop, x):
    """Mechanic name in the question → full name in the mechanic list (motorbike repair)."""
    if not x:
        return None
    if full := I._find_staff(shop, I.norm(x)):
        return full
    S = shop.t.get("staff")  # short name by last name ('a Đức'): only accepted when exactly one mechanic matches
    w = I.norm(x).split()[-1]
    c = [str(n) for n in (S["staff_name"].dropna() if S is not None and "staff_name" in S else []) if I.norm(str(n)).split()[-1] == w]
    return c[0] if len(c) == 1 else None


def _date(a, today):
    return _d(a["date"]) if a.get("date") else today


def _single_or_list(names, a):
    if a.get("single") or (a.get("k") in (None, 1) and a.get("single") is not False):
        return {"type": "string", "answer": names[0]}
    return {"type": "list", "answer": names}


def _top_products(s, a, t):
    p, k, by = _per(a, t), a.get("k") or 1, a.get("by") or "qty"
    names = R.top_products_by_profit(s, p, k) if by == "profit" else R.top_products(s, p, k, by)
    return _single_or_list(names, a)


def _share_or_num(s, a, t, v):
    return _pct(R.share(v, R.revenue(s, _per(a, t)))) if a.get("as_percent") else _num(v)


def _by_attr(s, a, t, attr):
    p, vals = _per(a, t), a.get("values") or []
    if isinstance(vals, str):
        vals = [vals]
    out = [R.revenue_by(s, p, attr, v) for v in vals]
    if a.get("as_percent"):
        return _pct(R.share(out[0], R.revenue(s, p)))
    return _num(out[0]) if len(out) == 1 else {"type": "list", "answer": out}


def _shift(s, a, t):
    p = _per(a, t)
    fn = R.shift_orders if a.get("metric") == "orders" else R.shift_revenue
    if a.get("compare_shift"):
        return _pct(R.pct_change(fn(s, p, "chieu"), fn(s, p, "sang")))
    return _num(fn(s, p, "sang" if str(a.get("shift", "")).lower().startswith("s") else "chieu"))


def _debt_total(s, a, t):
    x = _date(a, t)
    c = customer_key(s, a.get("customer"))
    if c is None:
        return _num(R.total_debt(s, x))
    O = R.debt_orders(s, x)
    return _num(int(round(O.loc[O["cust"] == c, "remaining"].sum())))


def _stock(s, a, t):
    x, k = _date(a, t), product_key(s, a["product"])
    # the model often puts the base unit (bottle, piece) into big_unit: if it cannot be converted, treat it as a plain stock question
    if a.get("big_unit") and R._factor(s, k, a["big_unit"]) != 1:
        return {"type": "list", "answer": R.stock_split(s, x, k, a["big_unit"])}
    return _num(R.stock_at(s, x, k))


def _expiring(s, a, t):
    start, end, mode = _d(a["start"]), _d(a["end"]), a.get("mode", "products")
    if mode == "value":
        return _num(R.expiring_value(s, t, start, end))
    if mode == "count_lots":
        return _num(int(len(R.expiring_lots(s, t, start, end))))
    names = R.expiring_products(s, t, start, end)
    return _num(len(names)) if mode == "count_products" else {"type": "list", "answer": names}


def _price_effect(s, a, t):
    k = product_key(s, a["product"])
    d = _d(a["date"]) if a.get("date") else None
    if d is None or d >= t:  # a price increase from today onward has no n days after it yet: the model copied "today" into date by mistake
        d = R.price_increase_date(s, k, a.get("new_price"))
    return _pct(R.price_effect(s, k, d, a["n"]))


def execute(shop, call, today):
    """call = {"tool": ..., ...parameters}. Bad parameters → abstain; Unanswerable → unanswerable."""
    name = call.get("tool")
    if name not in TOOLS:
        return {"type": "abstain"}
    try:
        return TOOLS[name][2](shop, call, today) or {"type": "abstain"}  # industry rules return None when they cannot compute
    except R.Unanswerable as e:
        if name[:3] in ("sx_", "dt_", "mb_"):  # wrong industry / missing ledger: usually the wrong tool was picked, not missing data
            return {"type": "abstain"}
        return {"type": "unanswerable", "reason": str(e)}
    except Exception:  # bad parameters / computation error on one question: abstain on that question, do not stop the whole run
        return {"type": "abstain"}


def call_schema():
    """JSON schema for constrained decoding (vLLM guided_json): one branch per tool, parameters in catalog order."""
    props = {
        "period": PERIOD_SCHEMA, "period2": PERIOD_SCHEMA,
        "compare": {"enum": ["previous", "same_period_last_month", "same_period_last_year", "before_tet", "last_year_tet", "other"]},
        "months": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}},
        "date": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
        "product": {"type": "string"}, "customer": {"type": "string"}, "group": {"type": "string"},
        "ingredient": {"type": "string"}, "staff": {"type": "string"}, "unit": {"type": "string"}, "big_unit": {"type": "string"},
        "cust_group": {"type": "string"}, "size": {"enum": ["M", "L"]}, "shift": {"enum": ["sang", "chieu"]},
        "metric": {"enum": ["revenue", "orders"]}, "by": {"enum": ["qty", "revenue", "profit", "orders", "days", "aov", "cancels", "amount", "count"]},
        "mode": {"enum": ["products", "count_products", "count_lots", "value"]},
        "values": {"type": "array", "items": {"type": "string"}},
        "buckets": {"type": "array", "items": {"type": "array", "items": {"type": ["integer", "null"]}}},
        "k": {"type": "integer"}, "n": {"type": "integer"}, "amount": {"type": "number"}, "new_price": {"type": "number"},
        "as_percent": {"type": "boolean"}, "single": {"type": "boolean"}, "rx": {"type": "boolean"}, "compare_shift": {"type": "boolean"},
        "reason": {"type": "string"},
        "job": _S, "weekday": _S, "model": _S, "family": _S, "brand": _S, "stage": {"type": "integer"}, "avg": {"type": "boolean"},
        "diaper_size": {"enum": ["NB", "S", "M", "L", "XL", "XXL"]},
        "what": {"enum": ["table", "top", "revenue", "turns", "days", "due_periods", "remaining", "overdue", "overdue_customers", "total",
                          "debtors", "aging", "count", "pct_sold", "top_model", "sold_seen", "new", "old", "brand_units", "new_revenue",
                          "voucher", "points", "ship", "qty", "top_brand", "top_brand_revenue"]},
    }
    return {"anyOf": [_obj({"tool": {"const": n}, **{p: props[p] for p in ps}, "reason": props["reason"]}, ["tool"])
                      for n, (_, ps, _) in TOOLS.items()]}


_PERIOD_ORDER = ["type", "date", "month", "quarter", "year", "n", "start", "end"]


def ordered(call):
    """Order keys as in the schema; few-shot examples in a different order teach the model to write fields that constrained decoding cannot go back to."""
    out = {"tool": call["tool"]}
    for p in TOOLS[call["tool"]][1] + ["reason"]:
        if p in call:
            v = call[p]
            out[p] = {k: v[k] for k in _PERIOD_ORDER if k in v} if p in ("period", "period2") else v
    return out


def catalog_text():
    return "\n".join(f"- {n}({', '.join(ps)}): {d}" for n, (d, ps, _) in TOOLS.items())
