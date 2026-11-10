"""Normalize raw values: money, dates, quantities, statuses, name keys."""
import datetime as dt
import math
import re
import unicodedata

EXCEL_EPOCH = dt.date(1899, 12, 30)


def is_blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def money(v):
    """'120,000' '50,500.0000' '25.000đ' '25k' '1tr440' '16,56tr' -53.500đ → number (int if whole)."""
    if is_blank(v):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = str(v).strip().lower().replace("đ", "").replace("vnd", "").replace(" ", "")
        neg = s.startswith("-")
        s = s.lstrip("-+")
        if m := re.fullmatch(r"(\d+)tr(\d{1,3})", s):  # 1tr440 = 1 440 000
            x = int(m[1]) * 1_000_000 + int(m[2].ljust(3, "0")) * 1000
        elif m := re.fullmatch(r"(\d+(?:[.,]\d+)?)tr", s):  # 16,56tr
            x = float(m[1].replace(",", ".")) * 1_000_000
        elif m := re.fullmatch(r"(\d+(?:[.,]\d+)?)k", s):
            x = float(m[1].replace(",", ".")) * 1000
        elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):  # 56,356,700 | 50,500.0000
            x = float(s.replace(",", ""))
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 1.016.000
            x = float(s.replace(".", ""))
        elif re.fullmatch(r"\d+(\.\d+)?", s):
            x = float(s)
        elif re.fullmatch(r"\d+,\d+", s):  # decimal comma
            x = float(s.replace(",", "."))
        else:
            return None
        x = -x if neg else x
    r = round(x)
    return int(r) if abs(x - r) < 1e-6 else x


def qty(v):
    """'3' | 3.0 | '3 chai' | '1 bao 25kg' → (number, unit or None)."""
    if is_blank(v):
        return None, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return money(v), None
    m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)\s*(.*)$", str(v))
    if not m:
        return None, None
    return money(m[1].replace(",", ".")), (m[2].strip() or None)


_MONTHS_YEAR = re.compile(r"(\d{1,2})\D+(\d{4})")


def sheet_year(sheet):
    """'T01_2025' '01.2025' 'Thang 02 2025' 'Tháng 01-2025' → 2025."""
    m = re.search(r"(20\d{2})", str(sheet or ""))
    return int(m[1]) if m else None


def date(v, year=None):
    """Returns (date, time|None). Accepts datetime, Excel serial, dd/mm/yyyy, yyyy-mm-dd[ hh:mm:ss], '1 thg 6 2025', 'd/m'."""
    if is_blank(v):
        return None, None
    if isinstance(v, dt.datetime):
        return v.date(), (v.time() if v.time() != dt.time(0) else None)
    if isinstance(v, dt.date):
        return v, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:
            return EXCEL_EPOCH + dt.timedelta(days=int(v)), None
        return None, None
    s = str(v).strip()
    if re.fullmatch(r"\d{5}(\.0)?", s):
        return date(float(s))
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s):
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
        t = dt.time(int(m[4]), int(m[5]), int(m[6] or 0)) if m[4] else None
        return d, (t if t != dt.time(0) else None)
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s):
        d = dt.date(int(m[3]), int(m[2]), int(m[1]))
        t = dt.time(int(m[4]), int(m[5]), int(m[6] or 0)) if m[4] else None
        return d, t
    if m := re.fullmatch(r"(\d{1,2})\s*thg\s*(\d{1,2})\s*,?\s*(\d{4})", s):
        return dt.date(int(m[3]), int(m[2]), int(m[1])), None
    if (m := re.fullmatch(r"(\d{1,2})/(\d{1,2})", s)) and year:
        return dt.date(year, int(m[2]), int(m[1])), None
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s):
        return None, dt.time(int(m[1]), int(m[2]), int(m[3] or 0))
    return None, None


def status(v):
    """Map to the 4 canonical statuses of rulebook §8: hoan_thanh | huy | tra_hang | dang_giao."""
    if is_blank(v):
        return None
    s = unicodedata.normalize("NFC", str(v)).lower().strip()
    if re.search(r"hủy|huỷ|huy\b|cancel|không giao được", s):
        return "huy"
    if re.search(r"trả|hoàn hàng|hoàn trả|return|đổi", s):
        return "tra_hang"
    if re.search(r"đang|chờ|shipping|gửi", s):
        return "dang_giao"
    return "hoan_thanh"


def key(s):
    """Name matching key: strip accents, lowercase, keep only letters/digits."""
    if is_blank(s):
        return ""
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9]", "", s)


_PHONE = re.compile(r"[\s\-–(]*\(?\+?0?\d[\d .]{7,}\d\)?\s*$")


def strip_phone(name):
    """'Đào Dương Giang - 0912 365 003' → 'Đào Dương Giang'."""
    if is_blank(name):
        return name
    return _PHONE.sub("", str(name)).strip(" -–()")


WALKIN = {"khachle", "kl", "le", "khachvanglai", "vanglai", ""}


def is_walkin(name):
    return key(name) in WALKIN


def _selftest():
    assert money("120,000") == 120000 and money("50,500.0000") == 50500
    assert money("25.000đ") == 25000 and money("-53.500đ") == -53500 and money("1.016.000đ") == 1016000
    assert money("25k") == 25000 and money("29200k") == 29200000 and money("-9k") == -9000
    assert money("1tr440") == 1440000 and money("9tr960") == 9960000 and money("16,56tr") == 16560000
    assert money("1,84tr") == 1840000 and money("2tr") == 2000000 and money(45000.0) == 45000 and money("abc") is None
    assert qty("1 bao 25kg") == (1, "bao 25kg") and qty("3") == (3, None) and qty(2.0) == (2, None) and qty("-1") == (-1, None)
    assert date("01/02/2025")[0] == dt.date(2025, 2, 1) and date(45689)[0] == dt.date(2025, 2, 1)
    assert date("45689")[0] == dt.date(2025, 2, 1) and date("1 thg 6 2025")[0] == dt.date(2025, 6, 1)
    assert date("1/1", 2026)[0] == dt.date(2026, 1, 1) and date("2025-02-01 06:00:25")[1] == dt.time(6, 0, 25)
    assert sheet_year("Tháng 01-2025") == 2025 and sheet_year("T06_2026") == 2026
    for raw, want in [("Đã hoàn thành", "hoan_thanh"), ("đã lấy", "hoan_thanh"), ("ok", "hoan_thanh"), ("Đã hoàn hàng", "tra_hang"),
                      ("Đổi trả", "tra_hang"), ("hàng trả về", "tra_hang"), ("returned", "tra_hang"), ("khách hủy", "huy"),
                      ("Không giao được", "huy"), ("Huỷ đơn", "huy"), ("cancelled", "huy"), ("Đang giao dịch", "dang_giao"),
                      ("Chờ giao", "dang_giao"), ("shipping", "dang_giao"), ("đang gửi", "dang_giao"), ("Đang xử lý", "dang_giao")]:
        assert status(raw) == want, (raw, status(raw))
    assert key("BIA TIGER 330 ML") == key("Bia Tiger 330ml") and key("Xúc  xích") == key("xúc xích")
    assert strip_phone("Đào Dương Giang - 0912 365 003") == "Đào Dương Giang"
    assert strip_phone("Hồ Minh Dương (0933201672)") == "Hồ Minh Dương" and strip_phone("Tô Nam Long 0919331756") == "Tô Nam Long"
    assert is_walkin("kl") and is_walkin("Khách lẻ") and is_walkin("lẻ") and not is_walkin("Lê Lan")
    print("parse selftest ok")


if __name__ == "__main__":
    _selftest()
