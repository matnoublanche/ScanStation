"""Run with python3 -m unittest discover -s tests on a ScanStation installation."""
import runpy
from pathlib import Path
import unittest
from PIL import Image, ImageDraw, ImageFont

engine = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scanstation"))


class ScanTests(unittest.TestCase):
    def test_faint_note_vetoes_visual_blank(self):
        page = Image.new("L", (1600, 2000), 255)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        ImageDraw.Draw(page).text((200, 500), "Retour accepté", font=font, fill=185)
        blank, _, _ = engine["inspect_page"](page.convert("RGB"))
        self.assertTrue(blank)
        self.assertTrue(engine["blank_has_text"](page))

    def test_drawing_is_kept_without_text(self):
        page = Image.new("RGB", (1000, 1200), "white")
        ImageDraw.Draw(page).ellipse((25, 30, 80, 90), outline="black", width=8)
        self.assertFalse(engine["inspect_page"](page)[0])

    def test_document_title_and_date(self):
        lines = [[("ACME", 97)], [("DEVIS", 95)], [("5 novembre 2026", 95)]]
        self.assertEqual(engine["document_name"](lines, False, "Scan"), "2026-11-05 - Devis - ACME")
