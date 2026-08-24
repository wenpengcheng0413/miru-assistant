from pathlib import Path

from miru_server.documents import extract


def test_extract_xlsx_with_sheet_values(tmp_path: Path):
    import openpyxl

    path = tmp_path / "sales.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "销售"
    book.active.append(["月份", "营收"])
    book.active.append(["八月", 120])
    book.save(path)

    result = extract(path, "spreadsheet")
    assert "工作表：销售" in result.text
    assert "八月 | 120" in result.text
    assert not result.error


def test_extract_pdf_creates_page_preview(tmp_path: Path):
    import fitz

    path = tmp_path / "note.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Miru PDF test")
    document.save(path)
    document.close()

    result = extract(path, "document", max_preview_pages=1)
    assert "Miru PDF test" in result.text
    assert len(result.previews) == 1
    assert Path(result.previews[0]).exists()
