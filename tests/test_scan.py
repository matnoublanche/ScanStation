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

    def test_curved_feeder_edge_preserves_print_and_corner_code(self):
        import numpy as np
        w, h = 900, 1200
        a = np.full((h, w, 3), 239, dtype=np.uint8)
        edge = (36 + 14*np.sin(np.arange(h)/145)).astype(int)
        for y, x in enumerate(edge):
            a[y, :x] = 148
        a[100:117, 64:81] = 20
        a[250:265, 150:620] = 148
        original = Image.fromarray(a)
        clean = engine["clear_backing"](original, np.asarray(original.convert("L")))
        self.assertEqual(clean.getpixel((12, 410)), (255,)*3)
        self.assertEqual(clean.getpixel((70, 106)), (20,)*3)
        self.assertEqual(clean.getpixel((200, 257)), (148,)*3)

    def test_slanted_fold_and_independent_mark(self):
        import numpy as np
        a = np.zeros((400, 760), dtype=np.uint8)
        x = np.arange(760)
        y = 200 + x//120
        a[y, x] = 55
        a[y[::100], x[::100]] = 90
        self.assertTrue(engine["fold_traces_only"](a))
        a[196:201, 450:455] = 105
        self.assertFalse(engine["fold_traces_only"](a))
