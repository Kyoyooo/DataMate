"""Read the shop README: column → canonical role, last data date, unit conversions, conventions."""
import datetime as dt
import re
from pathlib import Path

# (text pattern on the role description in the README, canonical key). Order matters: specific first, general after.
ROLE_RULES = [
    (r"^cột trống", None),
    (r"^mã đơn|^số hoá đơn|^số hóa đơn|^số thứ tự đơn", "order_id"),
    (r"^mã hàng", "product_id"),
    (r"^mã khách", "customer_id"),
    (r"^mã phiếu nhập", "receipt_id"),
    (r"^mã phiếu thu", "payment_id"),
    (r"^mã nhà cung cấp", "supplier_id"),
    (r"^mã nhân viên", "staff_id"),
    (r"^tên hàng|^hàng bán", "product_name"),
    (r"^tên khách", "customer_name"),
    (r"^tên$", "name"),
    (r"^số lượng đã đổi ra đơn vị cơ bản", "qty_base"),
    (r"^số lượng bán lấy từ lô", "lot_qty_base"),
    (r"^số lượng khách trả lại", "lot_return_base"),
    (r"^số lượng nhập \(đơn vị cơ bản\)", "in_qty_base"),
    (r"^số lượng nhập", "in_qty"),
    (r"^số lượng", "qty"),
    (r"^số thứ tự dòng trong phiếu nhập", "in_line_no"),
    (r"^số thứ tự dòng", "line_no"),
    (r"^đơn vị cơ bản", "base_unit"),
    (r"^đơn vị lớn", "big_unit"),
    (r"^đơn vị nhập", "in_unit"),
    (r"^đơn vị tính", "unit"),
    (r"^hệ số", "factor"),
    (r"^trạng thái đơn", "status"),
    (r"^trạng thái phiếu nhập", "receipt_status"),
    (r"^ngày bán", "order_date"),
    (r"^thời điểm đặt đơn|^giờ đặt đơn", "order_ts"),
    (r"^đơn giá", "unit_price"),
    (r"^thành tiền sau giảm|^thành tiền của dòng", "amount"),
    (r"^tiền giảm của cả dòng|^giảm giá của dòng", "line_discount"),
    (r"^giảm giá", "discount"),
    (r"^giá bán hiện tại", "price"),
    (r"^giá vốn", "cost"),
    (r"^nhóm hàng", "group"),
    (r"^nhóm khách", "cust_group"),
    (r"^số điện thoại", "phone"),
    (r"^địa chỉ", "address"),
    (r"^ngày nhập", "receipt_date"),
    (r"^nhà cung cấp", "supplier"),
    (r"^tổng tiền cả phiếu$", "amount"),  # motorbike repair ledger: money of the repair ticket (different from "total of the whole purchase receipt")
    (r"^tổng tiền phiếu nhập|^tổng tiền của cả phiếu|^tổng tiền cả phiếu", "receipt_total"),
    (r"^giá nhập", "in_price"),
    (r"^tiền nhập", "in_amount"),
    (r"^ghi chú", "note"),
    (r"^số lô", "lot"),
    (r"^hạn sử dụng", "expiry"),
    (r"^đã thanh toán|^khách đã trả cho cả đơn", "paid"),
    (r"^còn nợ|^số khách còn nợ|^khách còn nợ", "debt"),
    (r"^tổng tiền đơn|^số khách phải trả cho cả đơn|^khách cần trả cho cả đơn", "total_due"),
    (r"^tổng tiền hàng|^tiền hàng của đơn", "goods_total"),
    (r"^kênh bán", "channel"),
    (r"^hình thức thanh toán của đơn", "pay_method"),
    (r"^hình thức thanh toán", "pay_method"),
    (r"^thời điểm thu", "pay_ts"),
    (r"^số tiền khách trả cho cả đơn", "total_due"),
    (r"^số tiền", "pay_amount"),
    (r"^tồn kho", "stock_qty"),
    (r"^ngày giao", "delivery_date"),
    (r"^đợt giao", "delivery_no"),
    (r"^biển số", "plate"),
    (r"^tài xế", "driver"),
    (r"^số ngày được nợ", "credit_days"),
    (r"^hạn thanh toán", "due_date"),
    (r"^ngày bắt đầu áp dụng giá", "price_date"),
    (r"^giá bán áp dụng", "new_price"),
    (r"^giá trước lần đổi", "old_price"),
    (r"^hoạt chất", "ingredient"),
    (r"^thuốc kê đơn", "is_rx"),
    (r"^bàn$", "table_no"),
    (r"^khu vực", "area"),
    (r"^số khách của đơn", "guests"),
    (r"^ngày tạo", "created"),
    (r"^phí giao", "ship_fee"),
    (r"^tiền bớt", "discount"),
    (r"^tiền thu máy cũ", "trade_in"),
    (r"^imei", "imei"),
    (r"^ngày sửa", "order_date"),
    (r"^thợ làm phiếu", "staff_id"),
    (r"^các việc đã làm", "jobs"),
    (r"^dòng xe và biển số", "vehicle"),
    (r"^họ tên thợ", "staff_name"),
    (r"^phần trăm hoa hồng", "commission"),
    (r"^ngày vào làm", "hire_date"),
]


def role_key(desc):
    d = desc.strip().lower()
    for pat, k in ROLE_RULES:
        if re.search(pat, d):
            return k
    return "?" + d  # unknown: keep for reporting


def parse(path):
    """Returns dict: tables {file/sheet name: {column: key}}, data_end, conversions [(product name, big unit, factor, base unit)], notes, text."""
    text = Path(path).read_text(encoding="utf-8")
    tables, cur = {}, None
    for line in text.splitlines():
        if m := re.match(r"^## Cột trong `([^`]+)`(?:, sheet `([^`]+)`)?", line):
            cur = m[2] or m[1]
            tables[cur] = {}
        elif line.startswith("## "):
            cur = None
        elif cur and (m := re.match(r"^- \*\*(.+?)\*\*: (.+)$", line)):
            tables[cur][m[1]] = role_key(m[2])
    end = None
    if m := re.search(r"Dữ liệu có đến hết (\d{1,2})/(\d{1,2})/(\d{4})", text):
        end = dt.date(int(m[3]), int(m[2]), int(m[1]))
    conv = [(m[1].strip(), m[3].strip(), int(m[4]), m[5].strip())
            for m in re.finditer(r"^\s+- (.+?): (\d+) (.+?) = (\d+) (.+?)\s*$", text, re.M) if m[2] == "1"]
    notes = text[text.find("## Quy ước"):] if "## Quy ước" in text else ""
    return {"tables": tables, "data_end": end, "conversions": conv, "notes": notes, "text": text}


def table_key(name):
    """File/sheet name → list name: drop the extension, drop suffixes _1 / _2026."""
    stem = Path(name).stem if "." in name else name
    return re.sub(r"_(\d{1,2}|20\d{2})$", "", stem)


if __name__ == "__main__":
    import collections
    import sys
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "train/data")
    unknown = collections.Counter()
    for p in sorted(root.glob("*/README.md")):
        r = parse(p)
        for t, cols in r["tables"].items():
            for c, k in cols.items():
                if k and k.startswith("?"):
                    unknown[k] += 1
        print(p.parent.name, r["data_end"], len(r["tables"]), "bảng", len(r["conversions"]), "quy đổi")
    print("vai trò chưa ánh xạ:", dict(unknown))
