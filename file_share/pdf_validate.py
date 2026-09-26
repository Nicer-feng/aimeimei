"""Isolated, bounded PDF structure check. Invoked only with a local temporary file."""
import json
import re
import resource
import sys


def main(path):
    # A malformed object graph must not exhaust the shared web server.
    limit = 384 * 1024 * 1024
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (24 * 1024 * 1024, 24 * 1024 * 1024))
    from pypdf import PdfReader

    with open(path, 'rb') as source:
        data = source.read()
    if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
        return {'error': '文件不是完整的 PDF'}
    # Signature byte ranges must be patched into the original object bytes.
    # Any such marker is enough to reject editing, including malformed forms.
    if re.search(rb'/ByteRange\b|/Type\s*/Sig\b|/FT\s*/Sig\b', data):
        return {'error': '已签名 PDF 暂不支持页面整理'}
    del data
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        return {'error': '加密 PDF 暂不支持页面整理'}
    root = reader.trailer['/Root']
    for key in ('/Perms', '/AcroForm', '/Outlines', '/PageLabels', '/Names',
                '/Dests', '/StructTreeRoot', '/Threads', '/OpenAction', '/AA'):
        if root.get(key) is not None:
            return {'error': '含表单、书签或复杂导航结构的 PDF 暂不支持页面整理'}
    pages = len(reader.pages)
    if not 1 <= pages <= 100:
        return {'error': '仅支持 1–100 页 PDF'}
    for page in reader.pages:
        if float(page.get('/UserUnit', 1)) != 1:
            return {'error': '含特殊页面单位的 PDF 暂不支持页面整理'}
        if page.get('/AA') is not None:
            return {'error': '含自动动作的 PDF 暂不支持页面整理'}
        if page.get('/Annots') is not None:
            return {'error': '含注释或页面链接的 PDF 暂不支持页面整理'}
        box = page.mediabox
        if float(box.width) <= 0 or float(box.height) <= 0:
            return {'error': 'PDF 页面尺寸无效'}
    return {'pages': pages}


if __name__ == '__main__':
    try:
        result = main(sys.argv[1])
    except (Exception, MemoryError):
        result = {'error': 'PDF 结构校验失败，请确认文件可正常打开'}
    print(json.dumps(result, ensure_ascii=False), flush=True)
