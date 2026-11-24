"""Every product function, where it runs and its status — rows of the coverage matrix
(`docs/research/2026-11-23-r2-assembly-coverage-matrix.md`) brought up to the 2026-11-24 checklist."""

from __future__ import annotations

DRAMACLAW = "http://127.0.0.1:8080"
BACKLOT = "http://127.0.0.1:4750"
NEWAPI = "http://127.0.0.1:3000"

STATUS = {
    "ready": "Dùng được",
    "partial": "Dùng được, còn hạn chế",
    "soon": "Sắp có",
    "none": "Chưa có",
}

# (group, function, status, where it runs, link or "#start", note)
CATALOG: list[tuple[str, str, str, str, str, str]] = [
    ("Truyện", "Viết tiểu thuyết dài từ ý tưởng (huohuo)", "soon", "huohuo :18088", "", "M3"),
    ("Truyện", "Ý tưởng do app tự nghĩ (xoay vòng thể loại)", "soon", "huohuo", "", "M3"),
    ("Truyện", "Dịch truyện Trung → Việt, bảng tên Hán-Việt", "soon", "connector", "", "M3"),
    ("Truyện", "Viết truyện tiếng Việt (bộ máy của app cũ)", "soon", "ArcReel story-run API", "", "M3, D29"),
    ("Truyện", "Sách nói từ truyện", "none", "—", "", "M5"),
    (
        "Phim",
        "Phim kể chuyện từ một truyện có sẵn",
        "partial",
        "DramaClaw qua connector",
        "#start",
        "chất lượng hình giới hạn bởi model miễn phí",
    ),
    (
        "Phim",
        "Làm lại từ video có sẵn (file hoặc link)",
        "partial",
        "Whisper trên máy + DramaClaw",
        "#start",
        "video không lời: kể theo khung hình",
    ),
    ("Phim", "Phim kịch có thoại nhân vật", "soon", "huohuo formatter + DramaClaw", "", "M2"),
    ("Phim", "Chỉnh tay từng cảnh, canvas, nhân vật", "ready", "DramaClaw", DRAMACLAW, "mở dự án trong DramaClaw"),
    ("Phim", "Trợ lý chat Xia Director", "partial", "DramaClaw", DRAMACLAW, "hay hỏng trên model miễn phí"),
    ("Phim", "Hoàn thiện: phụ đề, âm lượng, nhạc nền", "soon", "post-stage", "", "M4"),
    ("Phim", "Báo cáo chất lượng (bộ kiểm tra của DramaClaw)", "soon", "DramaClaw verifiers", "", "M4"),
    (
        "Video ngắn",
        "Quảng cáo tiếp thị liên kết từ ảnh sản phẩm",
        "partial",
        "OpenMontage (agent)",
        BACKLOT,
        "đang thử; agent miễn phí chậm",
    ),
    (
        "Video ngắn",
        "Ảnh bối cảnh quảng cáo sản phẩm",
        "ready",
        "DramaClaw Freezone `ecommerce-ad`",
        DRAMACLAW,
        "tốn pool Seedream",
    ),
    (
        "Video ngắn",
        "Lồng tiếng Việt cho video có sẵn",
        "partial",
        "OpenMontage `localization-dub`",
        BACKLOT,
        "mới chạy tới điểm duyệt đầu",
    ),
    ("Video ngắn", "Cắt video dài thành clip ngắn", "soon", "OpenMontage `clip-factory`", BACKLOT, ""),
    ("Video ngắn", "Giải thích, tài liệu, hoạt hình", "soon", "OpenMontage", BACKLOT, ""),
    ("Video ngắn", "Đăng TikTok / YouTube kèm link", "soon", "Postiz", "", "mỗi bài bạn duyệt"),
    ("Vận hành", "Model, kênh và khoá API", "ready", "NewAPI", NEWAPI, ""),
    ("Vận hành", "Cấu hình model, lưu trữ media của DramaClaw", "ready", "DramaClaw → Cài đặt", DRAMACLAW, ""),
    ("Vận hành", "Theo dõi video OpenMontage", "partial", "Backlot", BACKLOT, "chỉ xem"),
    ("Vận hành", "Sao lưu, khôi phục, tự bật khi khởi động", "soon", "—", "", "M6"),
    ("Vận hành", "Theo dõi dung lượng ổ đĩa", "soon", "—", "", "M6"),
]
