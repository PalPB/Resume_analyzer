import io
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, DecodedStreamObject, NameObject

from utils.pdf_parser import extract_text_from_pdf


class PdfParserTests(unittest.TestCase):
    def test_extracts_text_from_generated_pdf(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)

        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 72 720 Td (Python FastAPI Developer) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                )
            }
        )

        output = io.BytesIO()
        writer.write(output)
        extracted = extract_text_from_pdf(output.getvalue())

        self.assertIn("Python FastAPI Developer", extracted)

    def test_reports_invalid_pdf_bytes(self):
        self.assertEqual(
            extract_text_from_pdf(b"not a pdf"),
            "__PDF_ERROR__:not a valid PDF file",
        )


if __name__ == "__main__":
    unittest.main()
