"""Deterministic local template matching and image-asset boundary tests."""
from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from autumn_genlogin.models import validated_steps
from autumn_genlogin.storage import Store
from autumn_genlogin.image_actions import ImageTemplateLibrary, find_image_center

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None


class ImageActionValidationTests(unittest.TestCase):
    def test_hash_id_and_confidence_validation(self):
        ident="a"*64
        step={"action":"click_image","template_id":ident,"confidence":0.94}
        self.assertEqual(validated_steps([step]),[step])
        for value in ("../../file.png","A"*64,"a"*63,"x"*64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validated_steps([dict(step,template_id=value)])
        for value in (False, "0.94", 0.89, 1.01, float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validated_steps([dict(step,confidence=value)])
        with self.assertRaises(ValueError):
            validated_steps([dict(step,path="C:/secrets.png")])


@unittest.skipUnless(HAS_CV,"opt-in OpenCV vision dependency is absent")
class OpenCVImageActionsTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import cv2
        self.np, self.cv2=np,cv2
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.lib=ImageTemplateLibrary(Store(self.root/"home"))
        rng=np.random.default_rng(49824)
        self.template=rng.integers(0,256,size=(32,40),dtype=np.uint8)
        self.screen=rng.integers(0,256,size=(180,260),dtype=np.uint8)
        self.screen[57:89,123:163]=self.template
        self.source=self.root/"target.png"
        self.source.write_bytes(self.png(self.template))
        self.image=self.png(self.screen)

    def png(self,array):
        ok, data=self.cv2.imencode(".png",array)
        self.assertTrue(ok)
        return data.tobytes()

    def test_sha_import_integrity_and_unique_match(self):
        ident=self.lib.import_png(self.source)
        self.assertEqual(ident,hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(self.lib.import_png(self.source),ident)
        self.assertEqual(self.lib.read(ident),self.source.read_bytes())
        self.assertEqual(find_image_center(self.image,self.lib.read(ident),0.94),(143.0,73.0))

    def test_unmatched_or_repeated_targets_refuse_click(self):
        distinct=self.np.random.default_rng(554).integers(
            0,256,size=self.screen.shape,dtype=self.np.uint8)
        with self.assertRaisesRegex(ValueError,"No sufficiently confident"):
            find_image_center(self.png(distinct),self.source.read_bytes(),0.94)
        # Two identical patterns have no unique click target.
        repeated=self.screen.copy()
        repeated[120:152,14:54]=self.template
        with self.assertRaisesRegex(ValueError,"Multiple matching images"):
            find_image_center(self.png(repeated),self.source.read_bytes(),0.94)

    def test_tampered_import_invalid_id_and_plain_colored_image(self):
        ident=self.lib.import_png(self.source)
        destination=self.lib.directory/(ident+".png")
        destination.write_bytes(self.png(self.screen[:32,:40]))
        with self.assertRaisesRegex(ValueError,"modified"):
            self.lib.read(ident)
        with self.assertRaisesRegex(ValueError,"Invalid image template"):
            self.lib.read("../escape")
        blank=self.root/"blank.png"
        blank.write_bytes(self.png(self.np.full((40,50), 255,dtype=self.np.uint8)))
        with self.assertRaisesRegex(ValueError,"Low-detail"):
            self.lib.import_png(blank)

    def test_incorrect_file_and_oversize_refused(self):
        self.source.write_bytes(b"not png")
        with self.assertRaisesRegex(ValueError,"PNG"):
            self.lib.import_png(self.source)
        self.source.write_bytes(b"\x89PNG\r\n\x1a\n"+b"z"*(256*1024))
        with self.assertRaisesRegex(ValueError,"exceeds"):
            self.lib.import_png(self.source)
        tiny=self.root/"tiny.png"
        tiny.write_bytes(self.png(self.template[:8,:8]))
        with self.assertRaisesRegex(ValueError,"dimensions"):
            self.lib.import_png(tiny)


if __name__=="__main__":
    unittest.main()
