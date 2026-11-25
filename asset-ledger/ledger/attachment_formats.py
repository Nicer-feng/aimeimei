"""附件 MIME 白名单与文件结构校验。"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
import re
import struct
from xml.etree import ElementTree
import zipfile
from zlib import crc32, error as CompressionError


@dataclass(frozen=True)
class AttachmentFormat:
    mime: str
    inline: bool


FORMATS = {
    ".pdf": AttachmentFormat("application/pdf", True),
    ".png": AttachmentFormat("image/png", True),
    ".jpg": AttachmentFormat("image/jpeg", True),
    ".jpeg": AttachmentFormat("image/jpeg", True),
    ".gif": AttachmentFormat("image/gif", True),
    ".webp": AttachmentFormat("image/webp", True),
    ".doc": AttachmentFormat("application/msword", False),
    ".docx": AttachmentFormat("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
    ".xls": AttachmentFormat("application/vnd.ms-excel", False),
    ".xlsx": AttachmentFormat("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
}

PACKAGE_CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
PACKAGE_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAIN_RELATIONSHIP = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
}
ZIP_XML_LIMIT = 256 * 1024
OOXML_MAIN_TAGS = {
    ".docx": (
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document",
        "{http://purl.oclc.org/ooxml/wordprocessingml/main}document",
    ),
    ".xlsx": (
        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
        "{http://purl.oclc.org/ooxml/spreadsheetml/main}workbook",
    ),
}
PDF_HEADER = re.compile(rb"%PDF-[0-9]\.[0-9][\r\n]")
PDF_TRAILER = re.compile(rb"[\r\n]startxref[ \t\r\n]+([0-9]{1,10})[ \t\r\n]+%%EOF\Z")
PDF_XREF = re.compile(rb"(?:xref(?=[ \t\r\n])|[0-9]+[ \t\r\n]+[0-9]+[ \t\r\n]+obj\b)")
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PNG_BIT_DEPTHS = {
    0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16),
}
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def extension(filename):
    return PurePath(filename).suffix.lower()


def valid_pdf(content):
    if not PDF_HEADER.match(content):
        return False
    trailer = PDF_TRAILER.search(content.rstrip())
    return trailer is not None and PDF_XREF.match(content, int(trailer[1]), trailer.start()) is not None


def valid_png(content):
    if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) < 45:
        return False
    size, kind, width, height, bits, color, compression, filtering, interlace = struct.unpack_from(
        ">I4sIIBBBBB", content, 8
    )
    if (size != 13 or kind != b"IHDR" or not width or not height or
            bits not in PNG_BIT_DEPTHS.get(color, ()) or compression or filtering or interlace > 1):
        return False
    view = memoryview(content)
    offset = 8
    has_pixels = False
    while offset + 12 <= len(content):
        size, kind = struct.unpack_from(">I4s", content, offset)
        end = offset + 8 + size
        if end + 4 > len(content) or crc32(view[offset + 4:end]) != struct.unpack_from(">I", content, end)[0]:
            return False
        if kind == b"IEND":
            return has_pixels and size == 0 and end + 4 == len(content)
        if kind == b"IDAT" and size:
            has_pixels = True
        offset = end + 4
    return False


def valid_jpeg(content):
    if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
        return False
    offset = 2
    has_frame = False
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            return False
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset + 3 > len(content):
            return False
        marker = content[offset]
        offset += 1
        if marker < 0xC0 or 0xD0 <= marker <= 0xD9:
            return False
        size = struct.unpack_from(">H", content, offset)[0]
        end = offset + size
        if size < 2 or end > len(content):
            return False
        if marker in JPEG_FRAME_MARKERS:
            if size < 11:
                return False
            height, width, components = struct.unpack_from(">HHB", content, offset + 3)
            if not height or not width or not components or size != 8 + 3 * components:
                return False
            has_frame = True
        if marker == 0xDA:
            return has_frame and size >= 8 and size == 6 + 2 * content[offset + 2] and end < len(content) - 2
        offset = end
    return False


def gif_color_table_size(flags):
    return 3 * (2 << (flags & 7)) if flags & 0x80 else 0


def gif_subblocks_end(content, offset):
    while offset < len(content):
        length = content[offset]
        offset += length + 1
        if not length:
            return offset
    return len(content)


def valid_gif(content):
    if len(content) < 14 or content[:6] not in (b"GIF87a", b"GIF89a") or content[-1:] != b";":
        return False
    if not all(struct.unpack_from("<HH", content, 6)):
        return False
    offset = 13 + gif_color_table_size(content[10])
    has_frame = False
    while offset < len(content):
        marker = content[offset]
        if marker == 0x3B:
            return has_frame and offset + 1 == len(content)
        if marker == 0x21:
            offset = gif_subblocks_end(content, offset + 2)
        elif marker == 0x2C and offset + 10 < len(content):
            if not all(struct.unpack_from("<HH", content, offset + 5)):
                return False
            offset += 10 + gif_color_table_size(content[offset + 9])
            if offset + 1 >= len(content) or not 2 <= content[offset] <= 8 or not content[offset + 1]:
                return False
            offset = gif_subblocks_end(content, offset + 1)
            has_frame = True
        else:
            return False
    return False


def valid_webp(content):
    if len(content) < 20 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        return False
    if struct.unpack_from("<I", content, 4)[0] + 8 != len(content):
        return False
    offset = 12
    has_pixels = False
    while offset + 8 <= len(content):
        kind, size = struct.unpack_from("<4sI", content, offset)
        start = offset + 8
        offset = start + size + (size & 1)
        if offset > len(content):
            return False
        if kind == b"VP8 ":
            has_pixels |= size > 10 and content[start + 3:start + 6] == b"\x9d\x01\x2a"
        elif kind == b"VP8L":
            has_pixels |= size > 5 and content[start] == 0x2F and content[start + 4] < 0x20
        elif kind == b"ANMF":
            has_pixels |= size > 24 and content[start + 16:start + 20] in (b"ALPH", b"VP8 ", b"VP8L")
    return has_pixels and offset == len(content)


def package_xml(archive, filename):
    member = archive.getinfo(filename)
    if not 0 < member.file_size <= ZIP_XML_LIMIT:
        raise ValueError("无效的 Office 包元数据。")
    with archive.open(member) as stream:
        content = stream.read(ZIP_XML_LIMIT + 1)
    if len(content) > ZIP_XML_LIMIT or has_doctype(content):
        raise ValueError("无效的 Office 包元数据。")
    return ElementTree.fromstring(content)


def has_doctype(content):
    return b"<!DOCTYPE" in content.replace(b"\0", b"").upper()


def package_main_tag(archive, member):
    # 只检查主部件开头，不解析全文、计算公式或加载外部关系。
    with archive.open(member) as stream:
        content = stream.read(32 * 1024)
    if has_doctype(content):
        return None
    parser = ElementTree.XMLPullParser(events=("start",))
    parser.feed(content)
    first = next(parser.read_events(), None)
    return first[1].tag if first is not None else None


def valid_office_package(content, suffix):
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                return False
            relations = package_xml(archive, "_rels/.rels")
            document_paths = [
                item.get("Target", "").lstrip("/") for item in relations.findall(PACKAGE_RELATIONSHIPS + "Relationship")
                if item.get("Type") in MAIN_RELATIONSHIP and item.get("TargetMode", "Internal") == "Internal"
            ]
            if len(document_paths) != 1:
                return False
            main_path = document_paths[0]
            if not main_path or "\\" in main_path or any(part in ("", ".", "..") for part in main_path.split("/")):
                return False
            member = archive.getinfo(main_path)
            if member.flag_bits & 1 or not member.file_size:
                return False
            types = package_xml(archive, "[Content_Types].xml")
            matching_types = [
                part.get("ContentType") for part in types.findall(PACKAGE_CONTENT_TYPES + "Override")
                if part.get("PartName") == "/" + main_path
            ]
            return (
                matching_types == [FORMATS[suffix].mime + ".main+xml"]
                and package_main_tag(archive, member) in OOXML_MAIN_TAGS[suffix]
            )
    except (KeyError, OSError, RuntimeError, ValueError, ElementTree.ParseError, zipfile.BadZipFile, CompressionError):
        return False


def valid_legacy_office(content, suffix):
    if not content.startswith(OLE_SIGNATURE):
        return False
    from ._vendor import olefile

    try:
        with olefile.OleFileIO(BytesIO(content), raise_defects=olefile.DEFECT_INCORRECT) as archive:
            if suffix == ".doc":
                if archive.get_type("WordDocument") != olefile.STGTY_STREAM:
                    return False
                with archive.openstream("WordDocument") as stream:
                    fib = stream.read(32)
                return len(fib) == 32 and fib.startswith(b"\xec\xa5")

            for name in ("Workbook", "Book"):
                if archive.exists(name) and archive.get_type(name) == olefile.STGTY_STREAM:
                    with archive.openstream(name) as stream:
                        bof = stream.read(8)
                    if len(bof) == 8:
                        record, size, version, category = struct.unpack("<HHHH", bof)
                        if record == 0x0809 and size >= 4 and version in (0x500, 0x600) and category == 5:
                            return True
            return False
    except (OSError, ValueError, IndexError, struct.error):
        return False


RASTER_VALIDATORS = {
    ".png": valid_png, ".jpg": valid_jpeg, ".jpeg": valid_jpeg, ".gif": valid_gif, ".webp": valid_webp,
}


def valid_attachment(content, suffix):
    if suffix == ".pdf":
        return valid_pdf(content)
    if suffix in RASTER_VALIDATORS:
        return RASTER_VALIDATORS[suffix](content)
    if suffix in (".docx", ".xlsx"):
        return valid_office_package(content, suffix)
    if suffix in (".doc", ".xls"):
        return valid_legacy_office(content, suffix)
    return False
