"""Genre packs (ADR-0119): what a genre asks of the plan and the prose, and the phrases it wears out.

A pack is data: planning guidance for the outline and chapter plans, craft rules for drafting, and fatigue phrases
that a chapter may use at most twice (a deterministic, stylistic check). A run picks the pack whose aliases its
brief's genre names, else the one the generated seed's genre names, else none. Donor surfaces: huohuo's per-genre
skill directories for premise, outline, brief and chapter writer (18 Chinese web-fiction genres) and shenbi
``genre-config`` (fatigue words, chapter types). Written in Vietnamese for Vietnamese readers; the catalog aims at every
known genre (sponsor, 2026-11-15; ``docs/r2/R2_CONTENT_FORMS_CATALOG.md``), huohuo's web-fiction genres included.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from server.story_authoring.checks import Finding, Severity

FATIGUE_LIMIT = 2


@dataclass(frozen=True)
class GenrePack:
    pack_id: str
    label: str
    aliases: tuple[str, ...]
    planning: tuple[str, ...]
    craft: tuple[str, ...]
    fatigue: tuple[str, ...]


PACKS: tuple[GenrePack, ...] = (
    # Specific genres come first: a genre text naming both ("võ hiệp" is also action) takes the specific pack.
    GenrePack(
        "revenge",
        "Báo thù – vả mặt",
        ("báo thù", "vả mặt", "trả thù", "phản đòn", "revenge"),
        (
            "Chương đầu dựng một màn bị chà đạp có người chứng kiến và cái giá thật; không kể suông 'bị coi thường'.",
            "Mỗi chương một nhịp: dồn ép, một đòn phản công nhỏ, đòn lớn để dành cho chương cuối.",
            "Món nợ được nêu một lần, rõ; kẻ thù trả đúng thứ đã cướp, không trả bằng một cái chết chung chung.",
        ),
        (
            "Màn lật ngược: kẻ kia thất thố bằng động tác cụ thể, rồi nhân vật chính một câu ép cả cảnh.",
            "Sau chiến thắng để nửa nhịp lặng; không họp lại để nhắc người đọc chuyện vừa xảy ra.",
        ),
        ("mặt tái mét", "run lẩy bẩy", "nụ cười nhếch môi", "khóe môi cong lên", "đừng hòng"),
    ),
    GenrePack(
        "angst",
        "Ngược luyến",
        ("ngược luyến", "ngược tâm", "angst"),
        (
            "Có một rào cản thật, không gỡ dễ (số phận, bệnh, thù nhà, lời thề); yêu nhau là phải trả giá.",
            "Mở bằng vài trang ngọt để rồi có cái mất; mỗi chương nặng thêm một nấc: kìm nén, đổ vỡ, mất mát.",
            "Người làm đau có nỗi khổ riêng; hiểu lầm gỡ xong cũng chưa thể hòa ngay.",
        ),
        (
            "Đau ở tự ái và điều không nói ra, hơn là máu và bệnh; chi tiết ngọt ban đầu quay lại thành vết cứa.",
            "Xen một mảnh dịu (kỷ niệm, giấc mơ) giữa những cảnh nặng để người đọc không chai.",
        ),
        ("trái tim như bị bóp nghẹt", "nước mắt rơi", "đau đến không thở nổi", "tan nát cõi lòng"),
    ),
    GenrePack(
        "ceo",
        "Tổng tài – hào môn",
        ("tổng tài", "hào môn", "thiếu gia", "tiểu thư nhà giàu", "ceo"),
        (
            "Chênh lệch thân phận là rào cản có hệ quả (hợp đồng, gia tộc, cổ phần), không chỉ chuyện giàu nghèo.",
            "Mỗi chương một cú đẩy: lộ một bí mật gia tộc hoặc một lần lựa chọn giữa tình và lợi.",
        ),
        (
            "Giàu sang hiện qua thói quen và thái độ của người xung quanh, không qua liệt kê đồ hiệu.",
            "Nam chính lạnh nhưng có lý do; chỉ hé mềm lòng qua một hành động nhỏ, đừng tuyên bố.",
        ),
        ("tổng tài lạnh lùng", "đôi mắt thâm trầm", "bá đạo ôm eo", "khí chất vương giả", "người đàn ông quyền lực"),
    ),
    GenrePack(
        "rebirth",
        "Xuyên không – trọng sinh",
        ("xuyên không", "trọng sinh", "xuyên sách", "hồi quy", "isekai", "reincarnation"),
        (
            "Nói rõ ngay: cách xuyên, thân phận mới, và một cái giá hay giới hạn của việc biết trước.",
            "Mở bằng khủng hoảng ngay lúc xuyên; mục tiêu đầu tiên là sống sót và đứng vững.",
            "Biết trước không thắng hộ: mỗi lần dùng nó phải gây hệ quả hoặc bị nghi ngờ.",
        ),
        (
            "Tư duy hiện đại va vào thế giới mới ở chuyện nhỏ cụ thể (bữa ăn, xưng hô, luật lệ), không bằng bài giảng.",
            "Lúc đầu nhân vật phải giấu mình; hành vi lạc thời đại có cái giá.",
        ),
        ("mở mắt ra", "nhớ lại kiếp trước", "ông trời cho cơ hội", "lần này sẽ khác", "ký ức ùa về"),
    ),
    GenrePack(
        "xianxia",
        "Tu tiên – tiên hiệp",
        ("tu tiên", "tiên hiệp", "tu chân", "tu luyện", "xianxia", "cultivation"),
        (
            "Cảnh giới, thọ nguyên và thiên kiếp có luật nhất quán; bậc cao vẫn có điểm yếu.",
            "Hai tuyến đi cùng nhau: lên cảnh giới và một món nợ nhân duyên hay đạo tâm.",
            "Chương cao trào có một lần đột phá hoặc đối đầu sinh tử, viết thành cảnh, không một câu 'y đã đột phá'.",
        ),
        (
            "Đột phá hiện qua thân thể, phản ứng của trời đất xung quanh và cái giá; không báo cáo cấp bậc.",
            "Câu văn gọn, ý cảnh qua mây, kiếm quang, hơi lạnh; tránh lời cảm thán hiện đại.",
        ),
        ("linh khí cuồn cuộn", "một ngụm máu tươi", "uy áp ập tới", "ánh mắt lạnh nhạt", "thiên tài vạn năm có một"),
    ),
    GenrePack(
        "wuxia",
        "Võ hiệp – kiếm hiệp",
        ("kiếm hiệp", "võ hiệp", "hiệp khách", "võ lâm", "wuxia"),
        (
            "Ân oán mở truyện (diệt môn, xuống núi, bị vu oan) có đích rõ; võ công có cái giá và khắc chế.",
            "Cốt là chữ hiệp: mỗi chương đặt nhân vật trước một lựa chọn giữa nghĩa và lợi hay thù.",
        ),
        (
            "Trận đấu lớn viết liền thành cảnh: chiêu qua lại, nội lực hao, dư chấn; không một câu 'phân thắng bại'.",
            "Lời thoại theo kiểu giang hồ xưa, không dùng từ mạng hay giá trị hiện đại.",
        ),
        ("nội lực dồn xuống đan điền", "kiếm quang lóe lên", "người trong giang hồ", "một chiêu chế địch"),
    ),
    GenrePack(
        "system",
        "Hệ thống – game",
        ("hệ thống", "game", "trò chơi", "lên cấp", "gamer", "litrpg"),
        (
            "Luật của hệ thống (cấp, kỹ năng, hồi chiêu, hình phạt khi chết) nêu sớm và không đổi giữa chừng.",
            "Mỗi chương gặp một ải khác loại (đánh, giải đố, lòng người); lỗ hổng khai thác được thì phải trả giá.",
            "Mạnh lên thể hiện qua cách thắng, không đổ chồng con số.",
        ),
        (
            "Bảng hệ thống, thông báo và nhiệm vụ đẩy truyện, mỗi lần ngắn; không dán nguyên bảng chỉ số dài.",
            "Con số tối đa vài dòng một cảnh; còn lại là hành động và phản ứng của người chơi khác.",
        ),
        ("ting! nhiệm vụ", "bảng thuộc tính", "kinh nghiệm tăng vọt", "trang bị cực phẩm"),
    ),
    GenrePack(
        "apocalypse",
        "Mạt thế – sinh tồn",
        ("mạt thế", "tận thế", "hậu tận thế", "sinh tồn", "zombie", "apocalypse"),
        (
            "Thảm họa có luật nhất quán (lây lan, điểm yếu); nước, thức ăn, thuốc có số lượng thật.",
            "Mỗi chương một chu trình: tìm đồ, gặp hiểm, thương lượng với người, lấy bỏ, rồi môi trường xấu thêm.",
            "Mối đe dọa gồm ngoài (quái, thiên tai), trong (nghi kỵ, thiếu hụt) và chính nhân vật (ranh giới đạo đức).",
        ),
        (
            "Người sống sót xám, không thánh nhân cũng không quỷ dữ; lòng tốt có cái giá.",
            "Cho 'tạm yên ổn' rồi phá bằng một tiếng động, một mùi hay một lần phản bội.",
        ),
        ("thế giới sụp đổ", "mùi máu tanh nồng", "lũ xác sống", "ánh mắt cảnh giác", "sống sót là trên hết"),
    ),
    GenrePack(
        "superpower",
        "Dị năng – siêu năng lực",
        ("dị năng", "siêu năng lực", "thức tỉnh", "người đột biến", "superpower"),
        (
            "Năng lực có ba ràng buộc: hao tổn, tác dụng phụ và một điểm yếu; không dùng miễn phí.",
            "Nhân vật chính thắng bằng mưu và dùng năng lực khéo, không bằng chỉ số cao hơn.",
        ),
        (
            "Thức tỉnh hoặc đấu dị năng viết thành cảnh có cảm giác cơ thể, cái giá và hậu quả quanh đó.",
            "Giữ người thường và dị năng yếu trong truyện; không ai cũng mạnh.",
        ),
        ("năng lượng bùng nổ", "thức tỉnh sức mạnh", "ánh sáng chói mắt", "sức mạnh vô tận"),
    ),
    GenrePack(
        "urban",
        "Đô thị",
        ("đô thị", "đô thị hiện đại", "công sở", "urban"),
        (
            "Bối cảnh có nghề, tiền thuê nhà, giờ làm cụ thể; xung đột nhỏ nhưng chạm sát đời sống.",
            "Mỗi chương một áp lực đời thường (nợ, việc, mối quan hệ) và một lựa chọn khiến nhân vật đổi.",
        ),
        (
            "Chi tiết địa điểm cụ thể (quán, tuyến xe, giờ cao điểm); không tả phố phường chung chung.",
            "Thoại ngắn, đúng cách nói của nghề và của vùng.",
        ),
        ("thành phố không bao giờ ngủ", "ánh đèn neon", "dòng người hối hả", "guồng quay cuộc sống"),
    ),
    GenrePack(
        "officialdom",
        "Quan trường – thương chiến",
        ("quan trường", "thương chiến", "thương trường", "chính trường", "officialdom", "business"),
        (
            "Cấp bậc, quy trình và quyền hạn đúng và nhất quán; không vượt cấp bằng quyền năng vô lý.",
            "Hai tuyến cùng chương: việc thực (dự án, đơn hàng, dân sinh) và đấu quyền hay đấu phe.",
            "Mỗi chương một nước cờ: ai nắm nguồn lực gì, ai mất gì nếu thua.",
        ),
        (
            "Thoại có tầng ẩn ý: nói ba phần giữ bảy phần; công khai, riêng tư và bàn tiệc khác giọng.",
            "Âm mưu lộ qua phản ứng gián tiếp; không để nhân vật tự khai hết kế hoạch.",
        ),
        ("ván cờ quyền lực", "cáo già", "nụ cười ẩn ý", "nước cờ cao tay", "thăng quan tiến chức"),
    ),
    GenrePack(
        "spy",
        "Gián điệp",
        ("gián điệp", "điệp viên", "tình báo", "điệp báo", "spy"),
        (
            "Luật nghề cố định: liên lạc đơn tuyến, mật mã, cái giá khi lộ; không chỗ nào hoàn toàn an toàn.",
            "Mỗi chương một vòng: nhiệm vụ, che giấu, bị thăm dò, thông tin thật giả, một lựa chọn đau.",
            "Cao trào đi qua ba tầng: khủng hoảng bề mặt, kẻ phản bội, rồi nhân vật chính lật lại thế cờ.",
        ),
        (
            "Nhân vật chính kìm nén; im lặng đáng sợ hơn lời thoại, ít gào thét hay ẩu đả.",
            "Cảnh thẩm vấn, thăm dò viết bằng chi tiết nhỏ (tách trà, giờ giấc, cách ngồi), để người đọc tự phát hiện.",
        ),
        ("ánh mắt sắc lạnh", "bóng người bám theo", "mồ hôi lạnh sau gáy", "không để lộ sơ hở"),
    ),
    GenrePack(
        "exorcism",
        "Trừ tà – tâm linh",
        ("trừ tà", "bắt quỷ", "pháp sư", "thầy pháp", "bùa chú", "exorcism"),
        (
            "Mỗi chương một vụ có manh mối ở hiện trường; đạo hạnh, bùa và pháp khí có hiệu lực nhất quán.",
            "Trận trừ tà đi qua đủ bốn bước: thăm dò, giao đấu, trả giá (tinh huyết, pháp khí nứt), dư chấn.",
        ),
        (
            "Mở chương bằng vật hay hiện tượng (nước đen rỉ qua khe cửa, lá bùa tự cháy), rồi vào việc ngay.",
            "Tránh 'kết quả rồi thu phục xong'; thắng phải có đổi chác.",
        ),
        ("âm khí nặng nề", "lá bùa tự bốc cháy", "oán khí ngút trời", "gió lạnh thổi qua", "một luồng sát khí"),
    ),
    GenrePack(
        "slowlife",
        "Điền văn – làm giàu",
        ("điền văn", "làm giàu", "làm ruộng", "slow life", "farming"),
        (
            "Mở bằng cảnh túng thiếu cụ thể (nợ, đói, nhà dột); mục tiêu trước mắt là no ấm và có vốn.",
            "Đi lên từng bước: khai khẩn, trồng nuôi, chế biến, bán, tích lũy; không giàu phi lý.",
            "Xung đột nhẹ: họ hàng, hàng xóm ganh tị, thời tiết, giá cả; không lấy bi kịch lớn.",
        ),
        (
            "Mùa, khói bếp, mùi cơm, việc đồng áng phải đúng và cụ thể.",
            "Mỗi cảnh một thu hoạch hay một chút ấm áp nhỏ; ơn nghĩa có chừng mực, không nuôi kẻ vô ơn.",
        ),
        ("khói bếp lượn lờ", "bát cơm nóng hổi", "cuộc sống bình yên", "ngày tháng êm đềm", "tiếng gà gáy"),
    ),
    GenrePack(
        "twist",
        "Não động – cú lừa",
        ("não động", "cú lừa", "plot twist", "twist", "kết thúc bất ngờ", "brainhole"),
        (
            "Một câu 'nếu như...' đặt ngay chương đầu; luật của nó công bằng, nhất quán và có hệ quả cực đoan.",
            "Cú lật phải được gài từ trước (chi tiết lệch, lời ai đó quên); lật được hai lớp thì tốt.",
            "Dù ý tưởng bay bổng, đích đến là cảm xúc và lựa chọn của một con người.",
        ),
        (
            "Viết nghiêm túc điều phi lý; không nháy mắt với người đọc.",
            "Ném manh mối nhỏ trong cảnh bình thường; khi lật, đối chiếu lại được từng chi tiết.",
        ),
        ("không ngờ rằng", "sự thật là", "hóa ra tất cả chỉ là", "mọi chuyện đều là kế hoạch", "bất ngờ thay"),
    ),
    GenrePack(
        "storytime",
        "Chuyện có thật – đời thường",
        ("chuyện có thật", "chuyện đời", "storytime", "confession"),
        (
            "Giọng ngôi thứ nhất như kể cho bạn nghe; mốc thời gian, nơi chốn và người trong cuộc rõ.",
            "Cái hố nhỏ, ai cũng từng gặp (hàng xóm, đồng nghiệp, người thân); mỗi chương một bước leo thang.",
            "Cuối truyện có một cú rẽ: sự thật khác điều đã tưởng, hoặc điều tôi học được.",
        ),
        (
            "Chi tiết vặt đáng tin (tin nhắn, số tiền, câu nói nguyên văn) hơn lời bình luận.",
            "Người kể nhận cả cái sai của mình; không làm người tốt hoàn hảo.",
        ),
        ("chuyện là thế này", "ai ngờ đâu", "tôi chết lặng", "đúng lúc đó", "không thể tin nổi"),
    ),
    GenrePack(
        "kids",
        "Thiếu nhi – cổ tích – ngụ ngôn",
        ("thiếu nhi", "cổ tích", "ngụ ngôn", "truyện trẻ em", "fairy tale", "fable", "kids"),
        (
            "Nhân vật chính (bé hay con vật) muốn một điều giản dị; có ba lần thử, mỗi lần khó hơn một chút.",
            "Điều hay rút ra từ việc nhân vật làm, kể bằng một câu ngắn, không giảng đạo.",
            "Nguy hiểm vừa phải và có người giúp; kết thúc yên lòng.",
        ),
        (
            "Từ ngữ đơn giản, câu ngắn, có lặp và vần nhẹ để đọc to; mỗi cảnh một hình ảnh dễ vẽ.",
            "Không cảnh rùng rợn, không từ nặng nề; cái ác chỉ là tính xấu có thể sửa.",
        ),
        ("ngày xửa ngày xưa", "từ đó trở đi", "sống hạnh phúc mãi mãi", "bài học quý giá"),
    ),
    GenrePack(
        "bedtime",
        "Truyện ngủ ngon",
        ("ngủ ngon", "ru ngủ", "trước khi ngủ", "bedtime", "cozy"),
        (
            "Không có kẻ thù hay hạn chót; điều đang bận tâm nhỏ và được giải bằng sự ấm áp, không bằng biến cố.",
            "Nhịp chậm dần qua ba chương; chương cuối là một cảnh nghỉ, tắt đèn, đi ngủ.",
        ),
        (
            "Viết bằng giác quan dịu: mùi, hơi ấm, tiếng mưa nhỏ, ánh đèn vàng; câu dài dần và mềm.",
            "Không treo cảnh, không kết bằng câu hỏi hay điều lo; đoạn cuối chậm và yên.",
        ),
        ("nhẹ nhàng chìm vào giấc ngủ", "bình yên lạ thường", "thời gian như ngừng trôi", "êm ái"),
    ),
    GenrePack(
        "family",
        "Tâm lý – gia đình",
        ("gia đình", "tâm lý", "đời thường", "family"),
        (
            "Xung đột nằm trong quan hệ: điều các nhân vật không nói với nhau, món nợ tình cảm, lựa chọn giữa bổn phận "
            "và mong muốn riêng.",
            "Mỗi chương đổi một chút cán cân quan hệ; cao trào là một cuộc đối mặt nói ra điều đã giấu.",
        ),
        (
            "Cảm xúc nằm trong đồ vật, bữa cơm, cử chỉ nhỏ; tránh độc thoại giải thích.",
            "Thoại gia đình đúng vai vế và cách xưng hô vùng miền.",
        ),
        ("nước mắt lăn dài", "nghẹn ngào", "trái tim thắt lại", "ấm áp lạ thường"),
    ),
    GenrePack(
        "mystery",
        "Trinh thám",
        ("trinh thám", "phá án", "bí ẩn", "điều tra", "mystery", "detective"),
        (
            "Gài manh mối công bằng: người đọc phải thấy được mọi manh mối trước khi lời giải được nói ra.",
            "Mỗi chương thêm một manh mối hoặc loại một nghi phạm; có ít nhất một hướng sai hợp lý.",
            "Lời giải đến từ suy luận của nhân vật, không từ lời thú tội hay sự trùng hợp.",
        ),
        (
            "Tả cụ thể chi tiết vật chứng; không nói thay người đọc điều chi tiết đó nghĩa là gì.",
            "Thẩm vấn và đối chất là cảnh, có thoại qua lại và phản ứng.",
        ),
        ("một linh cảm chẳng lành", "sống lưng lạnh toát", "mọi chuyện không đơn giản"),
    ),
    GenrePack(
        "horror",
        "Kinh dị",
        ("kinh dị", "ma", "tâm linh", "horror"),
        (
            "Nỗi sợ leo thang theo bậc: điều lạ nhỏ, rồi bằng chứng, rồi đối mặt; không tung hết ở chương đầu.",
            "Quy tắc của cái siêu nhiên nhất quán từ đầu đến cuối.",
        ),
        (
            "Sợ hãi qua giác quan: âm thanh, mùi, nhiệt độ, thứ lẽ ra không ở đó; không gọi tên nỗi sợ.",
            "Câu ngắn khi căng thẳng tăng.",
        ),
        ("rợn tóc gáy", "lạnh sống lưng", "một luồng khí lạnh", "bóng đen"),
    ),
    GenrePack(
        "romance",
        "Ngôn tình – tình cảm",
        ("ngôn tình", "tình cảm", "lãng mạn", "romance", "love"),
        (
            "Hai nhân vật có lý do thật để vừa hút nhau vừa ngăn nhau; trở ngại đến từ tính cách và hoàn cảnh.",
            "Mỗi chương đẩy quan hệ một nấc (gần lại hoặc rạn ra); khoảnh khắc lựa chọn ở cao trào.",
        ),
        ("Rung động qua chi tiết nhỏ và thoại có ẩn ý; tránh tả vẻ đẹp chung chung.",),
        ("tim đập thình thịch", "đôi mắt sâu thẳm", "nụ cười tỏa nắng", "má ửng hồng"),
    ),
    GenrePack(
        "action",
        "Hành động – phiêu lưu",
        ("hành động", "phiêu lưu", "giang hồ", "võ hiệp", "action", "adventure"),
        (
            "Mục tiêu và hạn chót rõ; mỗi chương có một trở ngại vật lý và cái giá phải trả.",
            "Nhân vật chính thắng bằng lựa chọn và sự khéo, không bằng may mắn.",
        ),
        ("Cảnh hành động: câu ngắn, động từ mạnh, không gian rõ để người đọc theo được ai ở đâu.",),
        ("nhanh như chớp", "trong chớp mắt", "không kịp phản ứng"),
    ),
    GenrePack(
        "fantasy",
        "Kỳ ảo – huyền huyễn",
        ("kỳ ảo", "huyền huyễn", "tiên hiệp", "phép thuật", "fantasy", "magic"),
        (
            "Phép thuật hay sức mạnh có luật và cái giá; xung đột đến từ giới hạn của nó.",
            "Thế giới hé dần qua hành động, không bằng đoạn giải thích dài.",
        ),
        ("Gọi tên sự vật của thế giới nhất quán; mỗi tên mới gắn với một cảnh dùng nó.",),
        ("sức mạnh khủng khiếp", "ánh sáng chói lòa", "uy áp kinh người"),
    ),
    GenrePack(
        "scifi",
        "Khoa học viễn tưởng",
        ("khoa học viễn tưởng", "viễn tưởng", "tương lai", "sci-fi", "science fiction"),
        ("Một ý tưởng khoa học trung tâm thay đổi đời sống nhân vật; xung đột là hệ quả của nó.",),
        ("Công nghệ hiện ra qua cách người dùng nó; không giảng giải.",),
        ("công nghệ tối tân", "vượt xa trí tưởng tượng"),
    ),
    GenrePack(
        "comedy",
        "Hài",
        ("hài", "hài hước", "comedy"),
        ("Tình huống hài đến từ mong muốn của nhân vật va vào hoàn cảnh; leo thang đến chỗ phi lý mà vẫn hợp lý.",),
        ("Nhịp: dựng – đẩy – cú chốt; thoại ngắn, đúng lúc; không giải thích chỗ buồn cười.",),
        ("cười ra nước mắt", "dở khóc dở cười"),
    ),
    GenrePack(
        "historical",
        "Lịch sử – cổ trang",
        ("lịch sử", "cổ trang", "dã sử", "historical"),
        ("Sự kiện bám bối cảnh thời đại; nhân vật có giới hạn của thời mình.",),
        ("Không dùng từ, đồ vật, thể chế của thời sau; xưng hô đúng thời.",),
        ("vạn người như một", "trời đất rung chuyển"),
    ),
    GenrePack(
        "school",
        "Học đường – thanh xuân",
        ("học đường", "thanh xuân", "tuổi học trò", "school", "youth"),
        ("Xung đột vừa tầm tuổi: thi cử, bạn bè, gia đình, lần đầu; mỗi chương một bước trưởng thành nhỏ.",),
        ("Thoại tuổi trẻ tự nhiên, không sáo; chi tiết trường lớp cụ thể.",),
        ("nắng sân trường", "thanh xuân rực rỡ", "tuổi trẻ nhiệt huyết"),
    ),
)


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def _names(folded: str, alias: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", folded) is not None


def pack_for(*genres: str) -> GenrePack | None:
    """The first pack an alias of which the given genre texts name as whole words, in the order given."""
    for genre in genres:
        folded = _fold(genre)
        for pack in PACKS:
            if any(_names(folded, alias) for alias in pack.aliases):
                return pack
    return None


def genre_menu() -> str:
    """The pack labels a seed chooses from when its brief names no pack."""
    return "; ".join(pack.label for pack in PACKS)


def planning_block(pack: GenrePack | None) -> str:
    if pack is None:
        return ""
    lines = "\n".join(f"- {rule}" for rule in pack.planning)
    return f"[Thể loại: {pack.label}]\n{lines}"


def craft_rules(pack: GenrePack | None) -> tuple[str, ...]:
    if pack is None:
        return ()
    words = ", ".join(f"'{w}'" for w in pack.fatigue)
    return (*pack.craft, f"Mỗi cụm sau tối đa {FATIGUE_LIMIT} lần trong một chương: {words}.")


def fatigue_findings(pack: GenrePack | None, scenes: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    """A genre's worn phrase used more than twice in a chapter (stylistic), placed in its first scene."""
    if pack is None:
        return ()
    findings: list[Finding] = []
    for phrase in pack.fatigue:
        count = sum(_fold(text).count(phrase) for _, text in scenes)
        if count > FATIGUE_LIMIT:
            node, text = next((n, t) for n, t in scenes if phrase in _fold(t))
            # The quote as the scene writes it (case kept), so a repair finds it verbatim.
            match = re.search(re.escape(phrase), unicodedata.normalize("NFC", text), re.IGNORECASE)
            quote = match.group(0) if match else phrase
            findings.append(Finding("GENRE_FATIGUE", Severity.STYLISTIC, node, f"'{phrase}' used {count} times", quote))
    return tuple(findings)


__all__ = ["PACKS", "GenrePack", "craft_rules", "fatigue_findings", "genre_menu", "pack_for", "planning_block"]
