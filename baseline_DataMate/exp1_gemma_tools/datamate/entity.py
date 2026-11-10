"""Find the product / group / customer named in the question using accent-free keys (longest substring match)."""
from functools import lru_cache

from .parse import key


def _catalog(shop):
    """→ {key: (code, display name)} from the catalog + names on sales lines."""
    out = {}
    L, P = shop.t.get("lines"), shop.t.get("products")
    if P is not None:
        for r in P.itertuples():
            nm = getattr(r, "name", None) or getattr(r, "product_name", None)
            if nm:
                out[key(nm)] = (getattr(r, "product_id", None), nm)
    if L is not None and "product_name" in L:
        vc = L.groupby("pkey")["product_name"].agg(lambda s: s.value_counts().index[0])
        pid = L.groupby("pkey")["product_id"].first() if "product_id" in L else {}
        for k, nm in vc.items():
            if k and k not in out:
                out[k] = (pid.get(k) if len(pid) else None, nm)
    return out


def products(shop):
    if not hasattr(shop, "_catalog"):
        shop._catalog = _catalog(shop)
    return shop._catalog


# Northern ↔ Southern regional words: the question may name an item differently from the data
REGIONAL = [("lon", "heo"), ("ran", "chien"), ("lac", "dau phong"), ("hoa qua", "trai cay"), ("gang tay", "bao tay"), ("trat", "to"),
            ("ca trau", "ca loc"), ("dua", "thom"), ("ngo", "bap"), ("bat", "chen"), ("coc", "ly"), ("tat", "vo"), ("mi chinh", "bot ngot"),
            ("vung", "me"), ("xi dau", "nuoc tuong"), ("coc sac", "cu sac"), ("ke", "gia do"), ("pho mat", "pho mai"), ("dau phu", "dau hu"), ("ngao", "ngheu"), ("trau", "loc")]


def find_product(shop, question):
    """Like _find_product; if nothing is found, try swapping regional words (má lợn → má heo)."""
    import re
    from .period import norm
    hit = _find_product(shop, question)
    if hit:
        return hit
    qn = norm(question)
    subs = [(x, y) for a, b in REGIONAL for x, y in ((a, b), (b, a)) if re.search(r"\b" + x + r"\b", qn)]
    for x, y in subs:
        hit = _find_product(shop, re.sub(r"\b" + x + r"\b", y, qn))
        if hit:
            return hit
    if len(subs) > 1:  # several regional words at once (đậu phụ rán → đậu hũ chiên)
        q2 = qn
        for x, y in subs:
            q2 = re.sub(r"\b" + x + r"\b", y, q2)
        return _find_product(shop, q2)
    return None


def _normed(shop):
    """[(key, code, name, normalized name padded with spaces)] — computed once per shop."""
    if not hasattr(shop, "_normed"):
        import re
        from .period import norm
        shop._normed = [(k, pid, nm, " " + re.sub(r"[^a-z0-9]+", " ", norm(nm)).strip() + " ") for k, (pid, nm) in products(shop).items()]
    return shop._normed


def _find_product(shop, question):
    """Product whose key is the longest one contained in the question (≥ 6 characters to avoid false matches). → (key, code, name) or None."""
    q = key(question)
    best = None
    for k, pid, nm, _ in _normed(shop):
        if len(k) >= 6 and k in q and (best is None or len(k) > len(best[0])):
            best = (k, pid, nm)
    if best is None:  # short names (đá 1x2, trà đá): match the whole phrase on the accent-free string
        import re
        from .period import norm
        qn = " " + re.sub(r"[^a-z0-9]+", " ", norm(question)) + " "
        for k, pid, nm, nn in _normed(shop):
            if len(nn.strip()) >= 4 and nn in qn and (best is None or len(nn) > len(best[0])):
                best = (nn, pid, nm)
        if best:
            best = (key(best[2]), best[1], best[2])
    if best is None:  # try matching by product code (SP0042)
        for k, pid, nm, _ in _normed(shop):
            if pid and key(pid) in q.split() or (pid and key(pid) in q):
                return k, pid, nm
    return best
