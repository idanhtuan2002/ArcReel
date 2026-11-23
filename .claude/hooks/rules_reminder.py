"""UserPromptSubmit: put the rules agents most often skip in front of every turn (AGENTS.md is the source)."""

from __future__ import annotations

import sys

REMINDER = """Quy tắc bắt buộc (AGENTS.md) trước mỗi việc:
0. GOAL (docs/GOAL.md) đứng trên mọi tài liệu: ghép nguyên phần tốt nhất của donor, chỉ kết nối và cấu hình, chất lượng ≥ donor, tự động, một người vận hành; làm theo docs/r2/ASSEMBLY_PLAN.md.
1. Research-first: đọc code/ADR hiện có, rồi mã nguồn donor ở commit cố định, rồi nguồn gốc; chỉ đưa phương án hoặc quyết định sau khi có bằng chứng (FACT/INFER).
2. Donor 整体移植: dùng cơ chế nào của donor thì lấy nguyên khối (code, prompt, cấu hình, test); chất lượng phải bằng hoặc hơn bản gốc; tự viết cần lý do ghi lại (Donor: trong commit).
3. Codebase-memory trước grep/Read khi tìm cấu trúc code (search_graph, trace_path, search_code).
4. Sửa theo lớp: quét mọi nơi dùng cùng trạng thái (Consumers: trong commit fix); ghi run bị chặn vào R2_RUN_BLOCK_LEDGER.md.
5. Cơ chế tự xây có chi phí lặp lại cần so với donor và sponsor duyệt. Trả lời bằng tiếng Việt."""


def main() -> int:
    sys.stdin.read()
    print(REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
