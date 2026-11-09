"""Genre packs (ADR-0119): what a genre asks of the plan and the prose, and the phrases it wears out.

A pack is data: planning guidance for the outline and chapter plans, craft rules for drafting, and fatigue phrases
that a chapter may use at most twice (a deterministic, stylistic check). A run picks the pack whose aliases its
brief's genre names, else the one the generated seed's genre names, else none. Donor surfaces: huohuo's per-genre
skill directories for premise, outline, brief and chapter writer (18 Chinese web-fiction genres) and shenbi
``genre-config`` (fatigue words, chapter types). The genres here are the ones Vietnamese readers buy, written in
Vietnamese; huohuo's cultivation, system and officialdom genres are market categories not carried over.
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


def pack_for(*genres: str) -> GenrePack | None:
    """The first pack an alias of which the given genre texts contain, in the order given."""
    for genre in genres:
        folded = _fold(genre)
        for pack in PACKS:
            if any(alias in folded for alias in pack.aliases):
                return pack
    return None


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


__all__ = ["PACKS", "GenrePack", "craft_rules", "fatigue_findings", "pack_for", "planning_block"]
