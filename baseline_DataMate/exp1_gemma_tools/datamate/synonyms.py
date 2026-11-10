"""Column name → role for files whose README does not list columns.

Lookup order: the shop's README → (list, column) in the table below / collected from other shops' READMEs → plain column name.
shortcut: hand-written dictionary for column names seen in train; a private set with unfamiliar names needs LLM column mapping (GPU step).
"""
from collections import Counter, defaultdict
from pathlib import Path

from .parse import key
from .readme import parse as parse_readme, table_key

# (list, column) → role. Lists compared with key() so spelling does not matter.
MANUAL_Q = {
    "SoQuy": {"Mã phiếu": "payment_id", "Thời gian": "pay_ts", "Mã hóa đơn": "order_id",
              "Phương thức thanh toán": "pay_method", "Giá trị": "pay_amount"},
    "DanhSachDonViTinh": {"Mã hàng": "product_id", "ĐVT": "big_unit", "Quy đổi": "factor", "Giá bán": "big_price"},
    "DanhSachHoaDon": {"Phương thức thanh toán": "pay_method", "Kênh bán": "channel", "Người bán": "staff_id",
                       "Thời gian": "order_date", "Thời gian tạo": "order_ts"},
    "DanhSachHoaDonChiTiet": {"Giá vốn": "cost", "Đơn vị tính": "unit"},
    "DanhSachSanPham": {"Giá vốn": "cost"},
    # SQLite POS
    "chi_nhanh": {"MaChiNhanh": "branch_id", "TenGoi": "name"},
    "nhan_vien": {"MaNhanVien": "staff_id", "TenGoi": "name", "ChucVu": "role"},
    "khach_hang": {"MaKhachHang": "customer_id", "TenGoi": "name", "SoDienThoai": "phone",
                   "LoaiKhachHang": "cust_group", "DiaChiLienHe": "address", "NamNu": "gender"},
    "nha_cung_cap": {"MaNhaCungCap": "supplier_id", "TenGoi": "name"},
    "san_pham": {"MaHangHoa": "product_id", "TenGoi": "name", "DanhMuc": "group", "DonViCoSo": "base_unit",
                 "GiaBanLe": "price", "GiaVonHang": "cost"},
    "don_vi_sp": {"MaHangHoa": "product_id", "DonViTinh": "big_unit", "HeSoQuyDoi": "factor", "GiaDonVi": "big_price"},
    "phieu_nhap": {"MaPhieuNhap": "receipt_id", "MaNhaCungCap": "supplier_id", "NgayNhapKho": "receipt_date",
                   "TinhTrang": "receipt_status", "TongGiaTriNhap": "receipt_total", "DienGiai": "note"},
    "chi_tiet_nhap": {"MaPhieuNhap": "receipt_id", "SoThuTu": "in_line_no", "MaHangHoa": "product_id",
                      "DonViTinh": "in_unit", "SL": "in_qty", "DonGiaNhap": "in_price", "MaLo": "lot", "HanSuDung": "expiry"},
    "don_hang": {"MaHoaDon": "order_id", "MaKhachHang": "customer_id", "MaNhanVien": "staff_id", "KenhBanHang": "channel",
                 "ThoiGianLap": "order_ts", "NgayLap": "order_date", "TinhTrang": "status", "TongTienHang": "goods_total",
                 "ChietKhau": "discount", "PhiVanChuyen": "ship_fee", "ThueGTGT": "vat", "TongThanhToan": "total_due",
                 "KhachDaTra": "paid", "ConPhaiThu": "debt", "PhuongThucTT": "pay_method", "MaKhuyenMai": "promo"},
    "chi_tiet_don": {"MaHoaDon": "order_id", "SoThuTu": "line_no", "MaHangHoa": "product_id", "DonViTinh": "unit",
                     "SL": "qty", "SLQuyDoi": "qty_base", "GiaDonVi": "unit_price", "ChietKhau": "discount",
                     "TriGia": "amount", "GiaVonLucBan": "cost"},
    "thanh_toan": {"MaPhieuThu": "payment_id", "MaHoaDon": "order_id", "NgayGioThu": "pay_ts", "SoTienThu": "pay_amount",
                   "PhuongThuc": "pay_method"},
    "tra_hang": {"MaPhieuTra": "return_id", "MaHoaDon": "order_id", "NgayGioTra": "return_ts", "NguyenNhan": "return_reason",
                 "TienHoanTra": "refund"},
    "the_kho": {"MaHangHoa": "product_id", "NgayGioPhatSinh": "move_ts", "LoaiGiaoDich": "move_type",
                "SLQuyDoi": "move_qty_base", "MaChungTu": "move_doc", "TonCuoi": "stock_after"},
    "lich_su_gia": {"MaHangHoa": "product_id", "NgayApDung": "price_date", "GiaBanLe": "new_price"},
    "lo_hang": {"MaHangHoa": "product_id", "MaLo": "lot", "MaPhieuNhap": "receipt_id", "HanSuDung": "expiry",
                "SLNhapQuyDoi": "in_qty_base", "DonGiaNhap": "lot_unit_cost"},
    "chi_tiet_don_lo": {"MaHoaDon": "order_id", "SoThuTu": "line_no", "MaLo": "lot", "SLQuyDoi": "lot_qty_base",
                        "SLTraQuyDoi": "lot_return_base"},
    "thong_tin_thuoc": {"MaHangHoa": "product_id", "ThanhPhanChinh": "ingredient", "BanTheoDon": "is_rx"},
    # Phone shop ledger
    "Ghi tắt": {"Ghi tắt": "alias", "Tên hàng": "name", "Loại": "group"},
    "SoBanHang": {"STT": "order_id", "Khách trả": "total_due", "Bớt": "discount", "Thu máy cũ": "trade_in",
                  "IMEI": "imei", "Giá": "unit_price"},
    "ThuMayCu": {"Giá thu": "trade_in", "Trừ vào (STT sổ bán)": "order_id", "Ngày": "?date", "Khách": "?cust", "SĐT": "?phone",
                 "IMEI": "?imei", "Máy thu": "?model", "Tình trạng": "?cond"},
    "Bảo hành": {"Ngày nhận": "warranty_date", "Máy": "model", "IMEI": "imei", "Ngày mua": "?buy", "Lỗi": "?err",
                 "Khách": "?cust", "SĐT": "?phone", "Xử lý": "?fix"},
    # Mixed file set BanHang_ / SoTay_
    "BanHang_BanTheoLo": {"Lô": "lot", "SL quy ra lẻ": "lot_qty_base", "SL trả (ĐVT cơ bản)": "lot_return_base",
                          "No.": "line_no", "Mã hóa đơn": "order_id"},
    "BanHang_ChiTietHoaDon": {"Giá vốn lúc bán": "cost", "SL cơ bản": "qty_base", "Khuyến mãi": "discount",
                              "Giá niêm yết": "unit_price", "Thanh tien": "amount", "Mã giao dịch": "order_id",
                              "Chi tiết hàng": "product_name", "Slg": "qty", "TT dòng": "line_no", "Ma hang": "product_id",
                              "Đ.vị": "unit"},
    "BanHang_DonViQuyDoi": {"Quy cách": "big_unit", "Mã vạch": "product_id", "Đơn vị": "big_unit", "Bằng": "factor", "Giá bán theo đơn vị quy đổi": "big_price",
                            "Mã sp": "product_id"},
    "BanHang_HangHoa": {"Giá lẻ": "price", "Tên hàng hóa": "name", "DVT": "base_unit", "Nhóm hàng": "group",
                        "Giá vốn hiện tại": "cost", "Phân loại": "group", "Món": "name", "ma_sp": "product_id",
                        "Giá": "price", "Đơn vị": "base_unit"},
    "BanHang_HoaDon": {"Đã thu": "paid", "Tên KH": "customer_name", "Trạng thái": "status", "Giờ tạo đơn": "order_ts",
                       "Mã NV bán": "staff_id", "Phương thức TT": "pay_method", "Ngày bán": "order_date",
                       "Nguồn đơn": "channel", "Còn nợ": "debt", "Mã KH mua": "customer_id",
                       "Tiền hàng trước giảm": "goods_total", "Tong tien": "total_due", "Order ID": "order_id", "CK": "discount"},
    "BanHang_KhachHang": {"Khách hàng mua": "name", "Kiểu khách": "cust_group", "Sinh nhật": "?birthday",
                          "Đối tượng KH": "?cust_type", "Hạng": "cust_group", "ten_kh": "name", "Số điện thoại": "phone", "Customer ID": "customer_id"},
    "BanHang_LichSuGia": {"Item": "product_name","Mã sản phẩm": "product_id", "Giá mới": "new_price", "Ngày áp dụng": "price_date",
                          "Sản phẩm": "product_name", "Giá cũ": "old_price"},
    "BanHang_LoHang": {"HSD": "expiry", "Mã món": "product_id", "SL nhập (ĐVT cơ bản)": "in_qty_base",
                       "Mã phiếu nhập": "receipt_id", "Lô": "lot"},
    "BanHang_PhieuThu": {"Mã thanh toán": "payment_id", "Ngày TT": "pay_ts", "Tiền thu": "pay_amount", "Ma don": "order_id","Số tiền thu": "pay_amount", "Mã bill": "order_id", "Phiếu thu": "payment_id",
                         "Thời gian thu": "pay_ts", "PTTT": "pay_method"},
    "BanHang_Thuoc": {"Mã HH": "product_id", "Hoạt chất": "ingredient", "Kê đơn": "is_rx"},
    "SoTay_ChiPhi": {"Ngày mua": "expense_date", "Tiền chi": "expense_amount", "Nhóm": "expense_cat", "Lưu ý": "note",
                     "Ghi chú": "note", "Ngày chi": "expense_date", "Mục": "expense_cat", "So tien": "expense_amount"},
    "SoTay_NhapHang": {"SL nhập": "in_qty", "Mô tả": "note", "Product": "product_name", "Thành tiền": "in_amount",
                       "Lô": "lot", "HSD": "expiry", "Ngày nhập": "receipt_date", "Nhà cung cấp": "supplier",
                       "ĐVT nhập": "in_unit", "Số phiếu": "receipt_id", "Giá nhập": "in_price"},
    "ton_kho": {"ma_sp": "product_id", "ten_hang": "product_name", "ĐVT": "base_unit","ID SP": "product_id", "Đơn vị": "base_unit", "Ton kho": "stock_qty", "Hàng hóa": "product_name"},
}

# Column names clear enough in any list (files without a "Cột trong" section in the README): used when the table above has nothing.
PLAIN = {"Đơn số": "order_id", "Ngày HĐ": "order_date", "Giờ tạo đơn": "order_ts", "Mã khách": "customer_id",
         "Mã KH mua": "customer_id", "Mã NV bán": "staff_id", "Nguồn": "channel", "Hình thức thanh toán": "pay_method",
         "Trạng thái giao": "status", "Tiền hàng trước giảm": "goods_total", "Tiền giảm": "discount",
         "Tổng thanh toán": "total_due", "Da tra": "paid", "Đã trả": "paid", "Công nợ": "debt", "SĐT": "phone",
         "Dòng": "line_no", "ĐV": "unit", "Barcode": "product_id", "Mã H.hóa": "product_id",
         "SL (ĐV cơ bản)": "qty_base", "Giá vốn lúc bán": "cost", "Thành tiền (đ)": "amount", "Lưu ý": "note"}

# Columns described only in the Conventions section of the README (no "Cột trong" section) — e.g. POS shops: roles taken from other shops' READMEs.
_HARVEST = None


KNOWN = Path(__file__).resolve().parent / "known_readmes"  # READMEs of the train set, packaged in the image


def _harvest(data_root):
    """Collect (list, column) → role from every shop README that lists columns (current set + train set); take the most common role."""
    q, plain = defaultdict(Counter), defaultdict(Counter)
    roots = [Path(data_root), KNOWN]
    for p in sorted(x for r in roots if r.exists() for x in r.glob("*/README.md")):
        for tname, cols in parse_readme(p)["tables"].items():
            for col, role in cols.items():
                q[(key(table_key(tname)), key(col))][role] += 1
                plain[key(col)][role] += 1
    out_q = {k: c.most_common(1)[0][0] for k, c in q.items()}
    out_plain = {k: c.most_common(1)[0][0] for k, c in plain.items() if c.most_common(1)[0][1] >= 2}
    for t, cols in MANUAL_Q.items():
        for col, role in cols.items():
            out_q[(key(t), key(col))] = role
    for col, role in PLAIN.items():
        out_plain.setdefault(key(col), role)
    return out_q, out_plain


def lookup(data_root):
    global _HARVEST
    if _HARVEST is None:
        _HARVEST = _harvest(data_root)
    return _HARVEST
