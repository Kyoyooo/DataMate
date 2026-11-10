"""Last step: keep an unanswerable answer only when certain (subjective / outside the data, or the shop really does not record that information)."""
import re

from .period import norm

_MISSING_HINTS = [(r"ton kho", r"ton kho|ton cuoi|\bton\b"), (r"gioi tinh", r"gioi tinh|namnu|nam nu"), (r"dia chi", r"dia chi"),
                  (r"ly do", r"ly do|nguyen nhan"), (r"thanh toan de tinh no|cong no|\bno\b", r"cong no|tra no|con no|da tra|tien thu|tra gop|\bgop\b|so no"),
                  (r"gia nhap|nhap hang", r"nhap"), (r"du lieu lo", r"\blo\b|so lo|han dung|hsd"), (r"pay_method", r"thanh toan|pttt"),
                  (r"channel", r"kenh|nguon"), (r"gia von", r"gia von"), (r"nhom khach", r"nhom khach|hang khach|kieu khach|loai khach|doi tuong"),
                  (r"chi phi", r"chi phi"), (r"nhom hang", r"\bnhom\b"), (r"ghi khach", r"khach")]


def vet_unanswerable(shop, res):
    """Keep unanswerable only when certain: subjective question, period outside the data, or the shop really never mentions that information."""
    if not res or res.get("type") != "unanswerable":
        return res
    why = norm(res.get("reason", ""))
    if re.search(r"chu quan|ngoai du lieu", why):
        return res
    text = norm(shop.readme["text"] + " " + " ".join(str(c) for _, c in shop.unknown_cols))
    for pat, hint in _MISSING_HINTS:
        if re.search(pat, why):
            return {"type": "abstain"} if re.search(hint, text) else res
    return {"type": "abstain"}  # other reason: not verified
