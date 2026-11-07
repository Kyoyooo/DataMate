# Rulebook (bộ fixture tổng hợp)

Hôm nay của mỗi câu là `as_of_date`. Bản ghi có ngày sau hôm nay coi như chưa xảy ra.

## Doanh thu và đơn hàng
- Doanh thu: tổng **Thành tiền** các dòng của đơn **không huỷ** và **không trả hàng**. Đơn đang giao vẫn tính.
- Số đơn: chỉ đếm đơn không huỷ, không trả hàng.
- Tỉ lệ đơn huỷ: phần trăm số đơn huỷ trên **mọi** đơn đặt trong kỳ.
- Khách lẻ không phải là khách: không xếp hạng, không có dòng trong bảng theo khách.

## Thời gian
- Tuần bắt đầu thứ Hai. **Tuần này**, **tháng này**: đến hết hôm nay. **Tuần rồi**: cả tuần liền trước.
- **N ngày gần nhất**: N ngày liền nhau, ngày cuối là hôm nay.
- Kỳ nằm **hoàn toàn** ngoài khoảng ngày có dữ liệu thì không trả lời được, không phải 0.

## Xếp hạng
- Bán chạy: theo tổng số lượng. Bằng nhau thì theo mã tăng dần.

## Đáp án
- Tiền làm tròn về đồng, nửa đồng làm tròn lên. Phần trăm làm tròn 2 chữ số thập phân.
- Câu hỏi nhiều số thì ghi list theo đúng thứ tự câu hỏi nêu.
