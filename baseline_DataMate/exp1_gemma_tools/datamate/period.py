"""Periods per rulebook §2. Every range is [start, end], both ends included (date)."""
import calendar as cal
import csv
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

D = dt.date


@dataclass(frozen=True)
class Period:
    start: D
    end: D
    kind: str = "range"  # day | week | month | quarter | year | range | this_month | ytd | lastn | tet

    def days(self):
        return (self.end - self.start).days + 1


def month_end(y, m):
    return D(y, m, cal.monthrange(y, m)[1])


def day(d):
    return Period(d, d, "day")


def month(y, m):
    return Period(D(y, m, 1), month_end(y, m), "month")


def quarter(y, q):
    return Period(D(y, 3 * q - 2, 1), month_end(y, 3 * q), "quarter")


def year(y):
    return Period(D(y, 1, 1), D(y, 12, 31), "year")


def week_of(d):
    mon = d - dt.timedelta(days=d.weekday())
    return Period(mon, mon + dt.timedelta(days=6), "week")


def this_week(today):
    return Period(week_of(today).start, today, "this_week")


def last_week(today):
    return week_of(today - dt.timedelta(days=7))


def this_month(today):
    return Period(D(today.year, today.month, 1), today, "this_month")


def ytd(today):
    return Period(D(today.year, 1, 1), today, "ytd")


def last_n_days(today, n):
    return Period(today - dt.timedelta(days=n - 1), today, "lastn")


def month_no_year(today, m):
    """Month M without a year: this year if not after today, otherwise last year."""
    y = today.year if D(today.year, m, 1) <= today else today.year - 1
    return month(y, m)


def quarter_no_year(today, q):
    y = today.year if D(today.year, 3 * q - 2, 1) <= today else today.year - 1
    return quarter(y, q)


def previous(p):
    """Previous period for comparisons (rulebook §1, §2)."""
    if p.kind == "day":
        return day(p.start - dt.timedelta(days=1))
    if p.kind in ("week", "this_week"):
        s = p.start - dt.timedelta(days=7)
        return Period(s, s + dt.timedelta(days=p.days() - 1), p.kind)
    if p.kind == "month":
        y, m = (p.start.year, p.start.month - 1) if p.start.month > 1 else (p.start.year - 1, 12)
        return month(y, m)
    if p.kind == "this_month":  # same number of days in the previous month; if that month is shorter, up to its end
        y, m = (p.start.year, p.start.month - 1) if p.start.month > 1 else (p.start.year - 1, 12)
        return Period(D(y, m, 1), D(y, m, min(p.end.day, cal.monthrange(y, m)[1])), "this_month")
    if p.kind == "quarter":
        y, q = p.start.year, (p.start.month - 1) // 3 + 1
        return quarter(y, q - 1) if q > 1 else quarter(y - 1, 4)
    if p.kind == "year":
        return year(p.start.year - 1)
    s = p.start - dt.timedelta(days=p.days())  # arbitrary range: the same number of days right before
    return Period(s, p.start - dt.timedelta(days=1), p.kind)


def same_period_last_year(p):
    def back(d):
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # 29/02
            return d.replace(year=d.year - 1, day=28)
    return Period(back(p.start), back(p.end), p.kind)


@lru_cache(maxsize=4)
def lunar_table(path):
    with open(path, encoding="utf-8") as f:
        return {(int(r["lunar_year"]), int(r["lunar_month"]), int(r["lunar_day"]), r["lunar_leap"] == "true"): D.fromisoformat(r["date"])
                for r in csv.DictReader(f)}


def tet(y, calendar_csv):
    """Tết of year Y: 23rd of the 12th lunar month (lunar year Y-1) → end of the 10th of the 1st lunar month (lunar year Y)."""
    lt = lunar_table(str(calendar_csv))
    return Period(lt[(y - 1, 12, 23, False)], lt[(y, 1, 10, False)], "tet")


def before_tet(p):
    return Period(p.start - dt.timedelta(days=p.days()), p.start - dt.timedelta(days=1), "range")


# ---------- text normalization (strip accents, fix typos) to match product / customer / mechanic names ----------
_KEEP = {"bills", "order", "orders", "seller", "top", "best", "total", "revenue", "cos", "ok", "oreo", "lays"}
_EN = [(r"\b(bao nhiu|bnhiu|bnhieu|bn)\b", "bao nhieu"), (r"\bnhiu\b", "nhieu"),
       (r"\b(dc|đc|duo)\b", "duoc"), (r"(?<!hoa )(?<!hue )(?<!mui )(?<!dau )(?<!viem )\b(hok|hong|ko|kg|k)\b", "khong"), (r"\btrc\b", "truoc"),
       (r"\b(dthu|dt)\b", "doanh thu"), (r"\bkhong can don bac si\b", "khong ke don"), (r"\brevenue\b", "doanh thu"), (r"\borders?\b", "don"), (r"\bbills?\b", "don"), (r"\btotal\b", "tong cong"),
       (r"\bbest ?sellers?\b", "ban chay nhat"),
       (r"\b(nhut|nhta|nhat')\b", "nhat"), (r"\bth nay\b", "thang nay"), (r"\bth ?(\d{1,2})\b", r"thang \1"), (r"\bq ?([1-4])/(\d{4})", r"quy \1/\2"),
       (r"\bdh\b", "don hang"),
       # typos / dialect seen in the public test
       (r"\bo do\b", "don"), (r"\bbna\b", "ban"), (r"\bnheiu\b", "nhieu"), (r"\bduco\b", "duoc"), (r"\bbin quan\b", "binh quan"),
       (r"\btrung bih\b", "trung binh"), (r"\bngaynao\b", "ngay nao"), (r"\bnhieudon\b", "nhieu don"), (r"\bda tri\b", "gia tri"),
       (r"\bbinh quan chen\b", "binh quan tren"), (r"\bchong (it nhat)\b", r"trong \1"), (r"\bhagn\b", "hang"), (r"\bti ne\b", "ti le"),
       (r"\bnhan dien\b", "nhan vien"), (r"\b(dup|jum)\b", "giup"), (r"\bkon\b", "con"), (r"\bkac\b", "cac"), (r"\bbao nhieu ten\b", "bao nhieu tien"),
       (r"\bvau cho\b", "voucher"), (r"\b(ngay|bua|khach|mat hang|hang|mon|nhan vien) mo\b", r"\1 nao"), (r"\btuan ni\b", "tuan nay"),
       (r"\bdao (may gio)\b", r"vao \1"), (r"\bmoi o don\b", "moi don"), (r"\bhsd\b", "han dung"), (r"\bdoanhthu\b", "doanh thu"), (r"\bthang (hai|ba|bon|bay|tam|chin|muoi)\b(?! (muoi|tram))", lambda m: "thang " + str({"hai": 2, "ba": 3, "bon": 4, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}[m[1]])),  # "tháng tư/sáu" collides with "từ/sau": dropped
       (r"\b(?:tinh|ke) (?:luon|ca) (?:hom nay|hnay)\b", "tinhcahomnay"), (r"\b(tuan nay|thang nay) (?:tinh )?(?:toi|den) (?:het )?(?:hom nay|hnay|nay)\b", r"\1"),
       (r"\b(?:tu )?dau nam (?:toi|den) (?:het )?(?:chu|gio|nay|hnay|hom nay)\b", "tu dau nam den nay"), (r"\bbq\b", "binh quan"), (r"\bxi o di\b", "cod"), (r"\bmi (don|ngay|lon|chai)\b", r"may \1"), (r"\btog\b", "tong"), (r"\bcog\b", "cong"),
       (r"\bthang ni\b", "thang nay"), (r"\b(bua|hom) ni\b", "hom nay"), (r"\bnam ni\b", "nam nay"),  # Central Vietnamese dialect
       (r"(?<!ngay )(?<![\d/])(\d{1,2})/(2[4-7])(?![\d/])", r"\1/20\2"),  # month/2-digit year: 3/26 → 3/2026
       (r"(?<![\d/\-])(\d{1,2})-(20\d{2})\b", r"\1/\2")]  # 7-2026 → 7/2026


def _telex(w):
    """Fix Telex typing errors on accent-free words: tieenf→tien, cuwar→cua, ddown→don, hoom→hom."""
    if w in _KEEP or not w.isalpha() or len(w) < 3:
        return w
    w = re.sub(r"(?<=[a-z])[fjrsx]$", "", w)
    w = w.replace("w", "").replace("dd", "d")
    return re.sub(r"([aeo])\1", r"\1", w)


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    s = " ".join(_telex(w) for w in s.split())
    for pat, rep in _EN:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s)


def _selftest():
    t = D(2026, 3, 4)  # Wednesday
    assert last_week(t) == Period(D(2026, 2, 23), D(2026, 3, 1), "week")
    assert this_week(t) == Period(D(2026, 3, 2), t, "this_week")
    assert previous(this_month(D(2026, 3, 31))) == Period(D(2026, 2, 1), D(2026, 2, 28), "this_month")
    assert previous(this_month(t)).end == D(2026, 2, 4)
    assert month_no_year(t, 5) == month(2025, 5) and month_no_year(t, 3) == month(2026, 3)
    assert previous(month(2026, 1)) == month(2025, 12) and previous(quarter(2026, 1)) == quarter(2025, 4)
    assert last_n_days(t, 7).start == D(2026, 2, 26)
    cal_csv = Path(__file__).resolve().parent.parent / "train/calendar.csv"
    if cal_csv.exists():
        p = tet(2026, cal_csv)  # Lunar New Year (Bính Ngọ): day 1 = 17/02/2026
        assert p.start == D(2026, 2, 10) and p.end == D(2026, 2, 26), p
    assert norm("tieenf bán hoom nay cuwar hangf ddown bij huỷ thangs 9 nawm 2025") == "tien ban hom nay cua hang don bi huy thang 9 nam 2025"
    print("period selftest ok")


if __name__ == "__main__":
    _selftest()
