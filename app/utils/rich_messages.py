from aiogram.types import (
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
)


def rich_message(title: str, *blocks) -> InputRichMessage:
    return InputRichMessage(
        blocks=[
            InputRichBlockSectionHeading(text=title, size=2),
            *blocks,
        ]
    )


def paragraph(text: str) -> InputRichBlockParagraph:
    return InputRichBlockParagraph(text=text)


def table(
    rows: list[list[RichBlockTableCell]],
    *,
    bordered: bool = True,
    striped: bool = True,
) -> InputRichBlockTable:
    return InputRichBlockTable(cells=rows, is_bordered=bordered, is_striped=striped)


def cell(
    text: object,
    *,
    is_header: bool = False,
    align: str = "left",
    colspan: int | None = None,
) -> RichBlockTableCell:
    return RichBlockTableCell(
        align=align,
        valign="middle",
        text=str(text),
        is_header=is_header,
        colspan=colspan,
    )


def key_value_rows(items: list[tuple[object, object]]) -> list[list[RichBlockTableCell]]:
    return [
        [cell(label, is_header=True), cell(value)]
        for label, value in items
    ]


def table_rows(
    headers: list[object],
    rows: list[list[object]],
    *,
    numeric_columns: set[int] | None = None,
) -> list[list[RichBlockTableCell]]:
    numeric_columns = numeric_columns or set()
    return [
        [cell(header, is_header=True, align="right" if index in numeric_columns else "left") for index, header in enumerate(headers)],
        *[
            [
                cell(value, align="right" if index in numeric_columns else "left")
                for index, value in enumerate(row)
            ]
            for row in rows
        ],
    ]
